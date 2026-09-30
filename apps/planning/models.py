import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def stage_image_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".jpg"
    return (
        f"projects/{instance.organization_id}/{instance.project_id}/stages/{instance.pk}{extension}"
    )


def validate_stage_image_size(file):
    if file.size > 5 * 1024 * 1024:
        raise ValidationError(_("L'image ne doit pas dépasser 5 Mo."))


def verification_report_reference():
    return f"PIVOT-VRF-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:10].upper()}"


class ProjectStage(models.Model):
    class Type(models.TextChoices):
        STANDARD = "standard", _("Standard")
        FOUNDATION = "foundation", _("Fondations")
        STRUCTURE = "structure", _("Structure")
        FINISHING = "finishing", _("Finitions")
        SAFETY = "safety", _("Sécurité")

    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        ACTIVE = "active", _("Active")
        COMPLETE = "complete", _("Terminée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="project_stages"
    )
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="stages")
    title = models.CharField("titre", max_length=200)
    stage_type = models.CharField(max_length=20, choices=Type.choices, default=Type.STANDARD)
    description = models.TextField("description", max_length=5000, blank=True)
    start_date = models.DateField("date de début")
    end_date = models.DateField("date de fin")
    estimated_cost = models.DecimalField(
        "coût estimé", max_digits=16, decimal_places=0, default=0, validators=[MinValueValidator(0)]
    )
    actual_cost = models.DecimalField(
        "coût réel", max_digits=16, decimal_places=0, default=0, validators=[MinValueValidator(0)]
    )
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    image = models.ImageField(
        "image",
        upload_to=stage_image_path,
        validators=[
            FileExtensionValidator(("jpg", "jpeg", "png", "webp")),
            validate_stage_image_size,
        ],
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_project_stages"
    )
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        ordering = ("start_date", "created_at")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="stage_end_not_before_start",
            ),
            models.CheckConstraint(
                condition=models.Q(estimated_cost__gte=0), name="stage_estimated_cost_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(actual_cost__gte=0), name="stage_actual_cost_non_negative"
            ),
        ]
        indexes = [models.Index(fields=("organization", "project", "status"))]

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La date de fin doit être postérieure au début."})
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError(_("L'étape doit appartenir à l'organisation du projet."))
        if self.created_by_id and not self.created_by.is_superuser:
            from apps.projects.models import ProjectMembership

            if not ProjectMembership.objects.filter(
                project_id=self.project_id,
                user_id=self.created_by_id,
                project_role__in=(
                    ProjectMembership.Role.ENGINEER,
                    ProjectMembership.Role.SITE_MANAGER,
                ),
            ).exists():
                raise ValidationError(_("Le créateur doit pouvoir gérer les étapes de ce projet."))

    def __str__(self):
        return f"{self.project} · {self.title}"

    @property
    def progress_percent(self):
        return {self.Status.PENDING: 0, self.Status.ACTIVE: 50, self.Status.COMPLETE: 100}[
            self.status
        ]

    @property
    def latest_declared_progress(self):
        return self.progress_declarations.order_by("-created_at").first()

    @property
    def latest_verified_progress(self):
        return self.progress_verifications.order_by("-created_at").first()

    @property
    def declared_progress_percent(self):
        record = self.latest_declared_progress
        return record.percent if record else None

    @property
    def verified_progress_percent(self):
        record = self.latest_verified_progress
        return record.percent if record else None

    @property
    def is_overdue(self):
        return self.status != self.Status.COMPLETE and self.end_date < timezone.localdate()


class StageProgressRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE)
    percent = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    evidence = models.ForeignKey(
        "collaboration.EvidenceRecord", on_delete=models.PROTECT, null=True, blank=True,
    )
    note = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        if self.stage_id and self.organization_id != self.stage.organization_id:
            raise ValidationError(_("La progression doit appartenir à l'organisation de l'étape."))
        if self.evidence_id and (
            self.evidence.organization_id != self.organization_id
            or self.evidence.project_id != self.stage.project_id
            or (self.evidence.stage_id and self.evidence.stage_id != self.stage_id)
        ):
            raise ValidationError(_("La preuve doit appartenir au même projet et à la même étape."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StageProgressDeclaration(StageProgressRecord):
    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE, related_name="progress_declarations")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_progress_declarations")


class StageProgressVerification(StageProgressRecord):
    stage = models.ForeignKey(ProjectStage, on_delete=models.CASCADE, related_name="progress_verifications")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_progress_verifications")
    declaration = models.OneToOneField(
        StageProgressDeclaration, on_delete=models.PROTECT, related_name="technical_verification",
        null=True, blank=True,
    )
    digital_verification = models.OneToOneField(
        "StageDigitalVerification", on_delete=models.PROTECT, related_name="technical_verification",
        null=True, blank=True,
    )
    quantities = models.JSONField(default=list, blank=True)
    reservations = models.JSONField(default=list, blank=True)
    logical_signature = models.CharField(max_length=64, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        super().clean()
        if not isinstance(self.quantities, list) or any(not isinstance(item, dict) for item in self.quantities):
            raise ValidationError({"quantities": "Les quantités doivent être une liste structurée."})
        required_quantity_keys = {"label", "quantity", "unit"}
        if any(not required_quantity_keys.issubset(item) for item in self.quantities):
            raise ValidationError({"quantities": "Chaque quantité exige un libellé, une quantité et une unité."})
        if not isinstance(self.reservations, list) or any(not isinstance(item, dict) for item in self.reservations):
            raise ValidationError({"reservations": "Les réserves doivent être une liste structurée."})
        required_reservation_keys = {"description", "status"}
        if any(not required_reservation_keys.issubset(item) for item in self.reservations):
            raise ValidationError({"reservations": "Chaque réserve exige une description et un statut."})
        if self.declaration_id and self.declaration.stage_id != self.stage_id:
            raise ValidationError(_("La déclaration technique doit appartenir à la même étape."))
        if self.digital_verification_id and self.digital_verification.declaration_id != self.declaration_id:
            raise ValidationError(_("Digital Verified ne correspond pas à cette déclaration."))


class StageTechnicalReview(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", _("Approuvée")
        CONDITIONAL = "conditional", _("Approuvée sous conditions")
        REJECTED = "rejected", _("Rejetée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    declaration = models.OneToOneField(
        StageProgressDeclaration, on_delete=models.PROTECT, related_name="technical_review"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_technical_reviews"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=1000)
    corrective_actions = models.TextField(max_length=3000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        if self.declaration_id and self.organization_id != self.declaration.organization_id:
            raise ValidationError(_("L'avis doit appartenir à l'organisation de la déclaration."))
        if not self.reason.strip():
            raise ValidationError({"reason": "Le motif de la décision est obligatoire."})
        if self.decision in {self.Decision.CONDITIONAL, self.Decision.REJECTED} and not self.corrective_actions.strip():
            raise ValidationError({"corrective_actions": "Les actions correctives sont obligatoires pour cette décision."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StageDigitalVerification(models.Model):
    class Result(models.TextChoices):
        PASSED = "passed", _("Digital Verified")
        FAILED = "failed", _("Échec de la vérification numérique")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    declaration = models.OneToOneField(
        StageProgressDeclaration, on_delete=models.PROTECT, related_name="digital_verification"
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="initiated_stage_digital_verifications"
    )
    result = models.CharField(max_length=12, choices=Result.choices)
    checks = models.JSONField(default=dict)
    examined_items = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        if self.declaration_id and self.organization_id != self.declaration.organization_id:
            raise ValidationError(_("La vérification doit appartenir à l'organisation de la déclaration."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StageSiteVisit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    stage = models.ForeignKey(ProjectStage, on_delete=models.PROTECT, related_name="site_visits")
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_site_visits")
    visited_at = models.DateTimeField()
    location_label = models.CharField(max_length=300, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    notes = models.TextField(max_length=2000, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-visited_at",)

    def clean(self):
        super().clean()
        if self.stage_id and self.organization_id != self.stage.organization_id:
            raise ValidationError(_("La visite doit appartenir à l'organisation de l'étape."))
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError(_("Latitude et longitude doivent être fournies ensemble."))
        if not self.location_label.strip() and self.latitude is None:
            raise ValidationError(_("Une localisation textuelle ou GPS est obligatoire."))
        if self.visited_at and self.visited_at > timezone.now():
            raise ValidationError({"visited_at": "Une visite réalisée ne peut pas être datée dans le futur."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StageSiteVerification(models.Model):
    class Result(models.TextChoices):
        PASSED = "passed", _("PIVOT Site Verified")
        CONDITIONAL = "conditional", _("Conforme sous réserves")
        FAILED = "failed", _("Non conforme")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    visit = models.OneToOneField(StageSiteVisit, on_delete=models.PROTECT, related_name="verification")
    technical_verification = models.ForeignKey(
        StageProgressVerification, on_delete=models.PROTECT, related_name="site_verifications"
    )
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stage_site_verifications")
    checklist = models.JSONField(default=list)
    evidence = models.ManyToManyField("collaboration.EvidenceRecord", related_name="site_verifications")
    reservations = models.JSONField(default=list, blank=True)
    result = models.CharField(max_length=16, choices=Result.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        if self.visit_id and self.organization_id != self.visit.organization_id:
            raise ValidationError(_("L'inspection doit appartenir à l'organisation de la visite."))
        if self.technical_verification_id and self.visit_id and self.technical_verification.stage_id != self.visit.stage_id:
            raise ValidationError(_("La vérification technique doit appartenir à l'étape visitée."))
        if not isinstance(self.checklist, list) or not self.checklist or any(
            not isinstance(item, dict) or not {"item", "result"}.issubset(item) for item in self.checklist
        ):
            raise ValidationError({"checklist": "La checklist structurée doit contenir au moins un contrôle."})
        if not isinstance(self.reservations, list) or any(
            not isinstance(item, dict) or not {"description", "status"}.issubset(item) for item in self.reservations
        ):
            raise ValidationError({"reservations": "Les réserves doivent être structurées."})
        if self.result in {self.Result.CONDITIONAL, self.Result.FAILED} and not self.reservations:
            raise ValidationError({"reservations": "Une conclusion avec réserves ou non conforme exige des réserves."})


class StageVerificationReport(models.Model):
    """Identité stable et traçable du rapport d'une vérification technique."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(
        max_length=40, unique=True, default=verification_report_reference, editable=False
    )
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    technical_verification = models.OneToOneField(
        StageProgressVerification, on_delete=models.PROTECT, related_name="report"
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="generated_stage_verification_reports",
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-generated_at",)

    def clean(self):
        super().clean()
        if (
            self.technical_verification_id
            and self.organization_id != self.technical_verification.organization_id
        ):
            raise ValidationError(_("Le rapport doit appartenir à l'organisation de la vérification."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StageInspectionRiskRule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="inspection_risk_rules")
    version = models.PositiveIntegerField()
    stage_types = models.JSONField(default=list, blank=True)
    minimum_stage_value = models.DecimalField(max_digits=16, decimal_places=0, default=0)
    maximum_progress_variance = models.PositiveSmallIntegerField(default=20, validators=[MaxValueValidator(100)])
    failed_history_threshold = models.PositiveSmallIntegerField(default=1)
    require_on_anomaly = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_inspection_risk_rules")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)
        constraints = [models.UniqueConstraint(fields=("organization", "version"), name="unique_inspection_risk_rule_version")]


class StageInspectionRiskAssessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    technical_verification = models.OneToOneField(StageProgressVerification, on_delete=models.PROTECT, related_name="risk_assessment")
    rule = models.ForeignKey(StageInspectionRiskRule, on_delete=models.PROTECT, related_name="assessments")
    inspection_required = models.BooleanField()
    reasons = models.JSONField(default=list)
    evaluated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspection_risk_assessments")
    created_at = models.DateTimeField(auto_now_add=True)


class StageInspectionRiskOverride(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.OneToOneField(StageInspectionRiskAssessment, on_delete=models.PROTECT, related_name="override")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspection_risk_overrides")
    reason = models.TextField(max_length=2000)
    confirmation = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
