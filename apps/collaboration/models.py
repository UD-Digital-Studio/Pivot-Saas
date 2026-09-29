import uuid

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _


def collaboration_path(instance, filename):
    return (
        f"projects/{instance.organization_id}/{instance.project_id}/"
        f"collaboration/{instance.pk}/{filename}"
    )


class ProjectDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        VERIFIED = "verified", _("Vérifié")
        APPROVED = "approved", _("Approuvé")
        REJECTED = "rejected", _("Rejeté")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="documents"
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=collaboration_path, max_length=255)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_documents"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_documents",
        null=True,
        blank=True,
    )
    review_reason = models.CharField(max_length=500, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-uploaded_at",)


class ProjectImage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="gallery_images"
    )
    image = models.ImageField(upload_to=collaboration_path, max_length=255)
    caption = models.CharField(max_length=300, blank=True)
    is_cover = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_project_images"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class EvidenceRecord(models.Model):
    class LocationStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", _("Non demandée")
        GRANTED = "granted", _("Autorisée")
        DENIED = "denied", _("Refusée")
        UNAVAILABLE = "unavailable", _("Indisponible")

    class Type(models.TextChoices):
        PHOTO = "photo", _("Photo")
        VIDEO = "video", _("Vidéo")
        INVOICE = "invoice", _("Facture")
        QUOTE = "quote", _("Devis")
        DELIVERY_NOTE = "delivery_note", _("Bon de livraison")
        MINUTES = "minutes", _("Compte rendu")
        INSPECTION = "inspection", _("Inspection")
        DOCUMENT = "document", _("Autre document")

    class Status(models.TextChoices):
        SUBMITTED = "submitted", _("Déposée")
        VERIFIED = "verified", _("Vérifiée")
        APPROVED = "approved", _("Approuvée")
        REJECTED = "rejected", _("Rejetée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    evidence_key = models.UUIDField(default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, related_name="evidence_records")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="evidence_records")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_evidence")
    stage = models.ForeignKey("planning.ProjectStage", on_delete=models.SET_NULL, null=True, blank=True, related_name="evidence_records")
    evidence_type = models.CharField(max_length=24, choices=Type.choices)
    title = models.CharField(max_length=200)
    description = models.TextField(max_length=3000, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.SUBMITTED)
    version = models.PositiveIntegerField(default=1)
    previous_version = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="next_versions")
    correction_reason = models.CharField(max_length=500, blank=True)
    is_administrative_correction = models.BooleanField(default=False)
    document = models.OneToOneField(ProjectDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="evidence_record")
    image = models.OneToOneField(ProjectImage, on_delete=models.SET_NULL, null=True, blank=True, related_name="evidence_record")
    uploaded_file = models.FileField(upload_to=collaboration_path, max_length=255, blank=True)
    preview_file = models.ImageField(upload_to=collaboration_path, max_length=255, blank=True)
    submission_id = models.UUIDField(unique=True, null=True, blank=True, editable=False)
    request_type = models.CharField(max_length=80, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    source_metadata = models.JSONField(default=dict, blank=True)
    location_consent = models.BooleanField(default=False)
    location_status = models.CharField(max_length=16, choices=LocationStatus.choices, default=LocationStatus.NOT_REQUESTED)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-captured_at",)
        constraints = [
            models.UniqueConstraint(fields=("evidence_key", "version"), name="unique_evidence_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="evidence_version_positive"),
            models.CheckConstraint(
                condition=~(models.Q(document__isnull=False) & models.Q(image__isnull=False)),
                name="evidence_single_legacy_source",
            ),
        ]
        indexes = [
            models.Index(fields=("organization", "project", "evidence_type")),
            models.Index(fields=("project", "status", "-captured_at")),
        ]

    def clean(self):
        super().clean()
        if self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError("La preuve doit appartenir à l'organisation du projet.")
        if self.author_id and not self.author.is_superuser:
            from apps.projects.models import ProjectMembership

            if not ProjectMembership.objects.filter(
                project_id=self.project_id,
                user_id=self.author_id,
                project_role__in=(
                    ProjectMembership.Role.OWNER,
                    ProjectMembership.Role.CONTRACTOR,
                    ProjectMembership.Role.SITE_MANAGER,
                    ProjectMembership.Role.ENGINEER,
                ),
            ).exists():
                raise ValidationError("L'auteur doit être un intervenant autorisé du projet.")
        for related, label in ((self.stage, "étape"), (self.document, "document"), (self.image, "photo")):
            if related and (
                related.organization_id != self.organization_id
                or related.project_id != self.project_id
            ):
                raise ValidationError(f"L'association {label} appartient à un autre projet.")
        if self.previous_version_id:
            if self.previous_version.project_id != self.project_id or self.previous_version.evidence_key != self.evidence_key:
                raise ValidationError("La version précédente doit appartenir à la même preuve.")
            if self.version != self.previous_version.version + 1:
                raise ValidationError("Le numéro de version doit suivre la version précédente.")
        if self.previous_version_id and not self.correction_reason.strip():
            raise ValidationError("Le motif de correction est obligatoire.")
        if bool(self.request_type) != bool(self.request_id):
            raise ValidationError("Le type et l'identifiant de la demande sont indissociables.")
        has_coordinates = self.latitude is not None or self.longitude is not None
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("La latitude et la longitude doivent être fournies ensemble.")
        if self.location_status == self.LocationStatus.GRANTED:
            if not self.location_consent or not has_coordinates:
                raise ValidationError("Une position autorisée exige le consentement et des coordonnées.")
            if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
                raise ValidationError("Les coordonnées sont hors limites.")
        elif has_coordinates or self.location_accuracy_m is not None:
            raise ValidationError("Les coordonnées ne sont conservées que lorsque la localisation est autorisée.")

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original and original.status in {self.Status.VERIFIED, self.Status.APPROVED}:
                protected = (
                    "evidence_key", "organization_id", "project_id", "author_id", "stage_id",
                    "evidence_type", "title", "description", "version", "previous_version_id",
                    "correction_reason", "is_administrative_correction", "document_id", "image_id",
                    "uploaded_file", "preview_file", "submission_id", "request_type", "request_id", "source_metadata",
                    "location_consent", "location_status", "latitude", "longitude", "location_accuracy_m",
                )
                if any(getattr(original, field) != getattr(self, field) for field in protected):
                    raise ValidationError("Une preuve validée est immuable. Créez une correction versionnée.")
                if original.status == self.Status.APPROVED and self.status != original.status:
                    raise ValidationError("Une preuve approuvée est immuable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in {self.Status.VERIFIED, self.Status.APPROVED}:
            raise ValidationError("Une preuve validée ne peut pas être supprimée.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.title} · v{self.version} · {self.get_evidence_type_display()}"


def _document_evidence_type(title):
    normalized = title.lower()
    for token, evidence_type in (
        ("facture", EvidenceRecord.Type.INVOICE),
        ("devis", EvidenceRecord.Type.QUOTE),
        ("livraison", EvidenceRecord.Type.DELIVERY_NOTE),
        ("inspection", EvidenceRecord.Type.INSPECTION),
        ("compte rendu", EvidenceRecord.Type.MINUTES),
        ("procès-verbal", EvidenceRecord.Type.MINUTES),
    ):
        if token in normalized:
            return evidence_type
    return EvidenceRecord.Type.DOCUMENT


@receiver(post_save, sender=ProjectDocument)
def register_document_evidence(sender, instance, created, **kwargs):
    if created:
        EvidenceRecord.objects.create(
            organization=instance.organization, project=instance.project,
            author=instance.uploaded_by, document=instance,
            evidence_type=_document_evidence_type(instance.title), title=instance.title,
            status=EvidenceRecord.Status.SUBMITTED,
            source_metadata={"legacy_model": "ProjectDocument"},
        )
    else:
        status_map = {
            ProjectDocument.Status.PENDING: EvidenceRecord.Status.SUBMITTED,
            ProjectDocument.Status.VERIFIED: EvidenceRecord.Status.VERIFIED,
            ProjectDocument.Status.APPROVED: EvidenceRecord.Status.APPROVED,
            ProjectDocument.Status.REJECTED: EvidenceRecord.Status.REJECTED,
        }
        EvidenceRecord.objects.filter(document=instance).update(status=status_map[instance.status])


@receiver(post_save, sender=ProjectImage)
def register_image_evidence(sender, instance, created, **kwargs):
    if created:
        EvidenceRecord.objects.create(
            organization=instance.organization, project=instance.project,
            author=instance.uploaded_by, image=instance,
            evidence_type=EvidenceRecord.Type.PHOTO,
            title=instance.caption or "Photo du chantier",
            status=EvidenceRecord.Status.SUBMITTED,
            source_metadata={"legacy_model": "ProjectImage"},
        )


class ProjectComment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_comments"
    )
    content = models.TextField(max_length=3000)
    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="deleted_project_comments",
        null=True,
        blank=True,
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
