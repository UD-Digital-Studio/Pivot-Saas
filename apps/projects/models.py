import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def validate_project_image_size(file):
    if file.size > 5 * 1024 * 1024:
        raise ValidationError(_("L'image ne doit pas dépasser 5 Mo."))


def project_cover_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".jpg"
    return f"projects/{instance.organization_id}/{instance.pk}/cover{extension}"


class Project(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        ONGOING = "ongoing", _("En cours")
        COMPLETE = "complete", _("Terminé")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="projects",
        verbose_name="organisation",
    )
    engineer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_projects",
        verbose_name="ingénieur responsable",
        null=True,
        blank=True,
    )
    name = models.CharField("nom", max_length=200)
    description = models.TextField("description", max_length=5000, blank=True)
    location = models.CharField("localisation", max_length=200)
    project_date = models.DateField("date du projet")
    status = models.CharField(
        "statut",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    budget_amount = models.DecimalField(
        "budget",
        max_digits=16,
        decimal_places=0,
        default=0,
        validators=[MinValueValidator(0)],
    )
    cover_image = models.ImageField(
        "image de couverture",
        upload_to=project_cover_path,
        validators=[validate_project_image_size],
        blank=True,
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "projet"
        verbose_name_plural = "projets"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(budget_amount__gte=0),
                name="project_budget_non_negative",
            )
        ]
        indexes = [
            models.Index(fields=("organization", "status")),
            models.Index(fields=("organization", "-updated_at")),
        ]

    def clean(self):
        super().clean()
        if self.engineer_id:
            if self.engineer.organization_id != self.organization_id:
                raise ValidationError(
                    {"engineer": "L'ingénieur doit appartenir à l'organisation du projet."}
                )
            if self.engineer.role != self.engineer.Role.ENGINEER:
                raise ValidationError({"engineer": "Le responsable doit avoir le rôle ingénieur."})

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("projects:detail", kwargs={"pk": self.pk})


class ProjectMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("Propriétaire du chantier")
        CONTRACTOR = "contractor", _("Entrepreneur")
        SITE_MANAGER = "site_manager", _("Responsable de chantier")
        ENGINEER = "engineer", _("Ingénieur")
        PIVOT_REVIEWER = "pivot_reviewer", _("Vérificateur PIVOT")

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="project_memberships",
        verbose_name="organisation",
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="projet",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="project_memberships",
        verbose_name="membre",
    )
    project_role = models.CharField("rôle projet", max_length=24, choices=Role.choices)
    created_at = models.DateTimeField("affecté le", auto_now_add=True)

    class Meta:
        ordering = ("user__username",)
        verbose_name = "affectation projet"
        verbose_name_plural = "affectations projet"
        constraints = [
            models.UniqueConstraint(
                fields=("project", "user"),
                name="unique_project_membership",
            ),
            models.UniqueConstraint(
                fields=("project",),
                condition=models.Q(project_role="owner"),
                name="unique_project_owner_role",
            ),
        ]
        indexes = [models.Index(fields=("organization", "user"))]

    def clean(self):
        super().clean()
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError(_("L'affectation doit appartenir à l'organisation du projet."))

    def __str__(self):
        return f"{self.user} · {self.project}"


class ProjectOwnership(models.Model):
    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="ownership", verbose_name="projet"
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="project_ownerships",
        verbose_name="organisation",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_project_confirmations",
        verbose_name="propriétaire",
    )
    is_confirmed = models.BooleanField("confirmé", default=False)
    confirmed_at = models.DateTimeField("confirmé le", null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="confirmed_project_ownerships",
        null=True,
        blank=True,
        verbose_name="confirmé par",
    )
    terms_version = models.CharField("version des conditions", max_length=40, blank=True)
    terms_accepted = models.BooleanField("conditions acceptées", default=False)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "ownership du projet"
        verbose_name_plural = "ownerships des projets"

    @property
    def is_valid(self):
        return bool(
            self.is_confirmed
            and self.terms_accepted
            and self.confirmed_at
            and self.confirmed_by_id == self.owner_id
            and self.project.memberships.filter(
                user_id=self.owner_id, project_role=ProjectMembership.Role.OWNER
            ).exists()
        )

    def clean(self):
        super().clean()
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError(_("L'ownership doit appartenir à l'organisation du projet."))


class ProjectOwnershipHistory(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="ownership_history")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    previous_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="previous_project_ownerships",
        null=True,
        blank=True,
    )
    new_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="new_project_ownerships",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_ownership_changes",
    )
    reason = models.CharField("motif", max_length=500)
    created_at = models.DateTimeField("modifié le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class ProjectAuthorityMigrationReview(models.Model):
    class Reason(models.TextChoices):
        NO_CLIENT = "no_client", _("Aucun client affecté")
        MULTIPLE_CLIENTS = "multiple_clients", _("Plusieurs clients affectés")

    class Status(models.TextChoices):
        OPEN = "open", _("À examiner")
        RESOLVED = "resolved", _("Résolu")

    project = models.OneToOneField(
        Project,
        on_delete=models.PROTECT,
        related_name="authority_migration_review",
        verbose_name="projet",
    )
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="authority_migration_reviews",
        verbose_name="organisation",
    )
    reason = models.CharField("motif", max_length=32, choices=Reason.choices)
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.OPEN
    )
    candidate_user_ids = models.JSONField("clients candidats", default=list, blank=True)
    detected_at = models.DateTimeField("détecté le", auto_now_add=True)
    resolved_at = models.DateTimeField("résolu le", null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="resolved_authority_migration_reviews",
        null=True,
        blank=True,
    )
    resolution_note = models.CharField("note de résolution", max_length=500, blank=True)

    class Meta:
        ordering = ("status", "project__name")
        verbose_name = "revue de migration d'autorité"
        verbose_name_plural = "revues de migration d'autorité"


class ProjectOnboarding(models.Model):
    class Route(models.TextChoices):
        CLIENT_LED = "client_led", _("Initié par le client")
        CONTRACTOR_LED = "contractor_led", _("Initié par l'entrepreneur")
        PIVOT_LED = "pivot_led", _("Initié par PIVOT")

    class Status(models.TextChoices):
        DRAFT = "draft", _("À compléter")
        READY = "ready", _("Prêt à activer")
        ACTIVE = "active", _("Activé")

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="onboarding"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="project_onboardings"
    )
    route = models.CharField(max_length=24, choices=Route.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    financial_conditions = models.TextField(max_length=3000)
    conditions_version = models.CharField(max_length=40, default="2026-09-v1")
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="initiated_project_onboardings"
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="activated_project_onboardings", null=True, blank=True
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectConciergeFollowUp(models.Model):
    onboarding = models.OneToOneField(
        ProjectOnboarding, on_delete=models.CASCADE, related_name="concierge_follow_up"
    )
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE,
        related_name="project_concierge_follow_ups",
    )
    pivot_agent = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="concierge_projects",
    )
    training_completed = models.BooleanField(default=False)
    friction = models.CharField(max_length=1000, blank=True)
    next_action = models.CharField(max_length=1000)
    next_action_due_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="updated_concierge_follow_ups",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.onboarding_id and self.organization_id != self.onboarding.organization_id:
            raise ValidationError(_("Le suivi concierge doit appartenir à l’organisation du projet."))
        if self.pivot_agent_id and not self.pivot_agent.is_superuser:
            raise ValidationError({"pivot_agent": "L’agent concierge doit être un super-administrateur PIVOT."})
        if self.updated_by_id and not self.updated_by.is_superuser:
            raise ValidationError({"updated_by": "La mise à jour doit être effectuée par PIVOT."})
        if not self.next_action.strip() and self.onboarding.status != ProjectOnboarding.Status.ACTIVE:
            raise ValidationError({"next_action": "La prochaine action est obligatoire avant l’activation."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectTermsVersion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="terms_versions")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    budget_amount = models.DecimalField(max_digits=16, decimal_places=0)
    currency = models.CharField(max_length=3, default="XAF")
    financial_conditions = models.TextField(max_length=3000)
    authority_owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="project_terms_authorities")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_project_terms")
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-version",)
        constraints = [
            models.UniqueConstraint(fields=("project", "version"), name="unique_project_terms_version"),
            models.UniqueConstraint(fields=("project",), condition=models.Q(is_current=True), name="unique_current_project_terms"),
        ]


class ProjectActorConfirmation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        ACCEPTED = "accepted", _("Acceptée")
        REJECTED = "rejected", _("Refusée")
        EXPIRED = "expired", _("Expirée")

    terms_version = models.ForeignKey(ProjectTermsVersion, on_delete=models.CASCADE, related_name="actor_confirmations")
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="actor_confirmations")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_actor_confirmations")
    project_role = models.CharField(max_length=24, choices=ProjectMembership.Role.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("terms_version", "user", "project_role"), name="unique_actor_confirmation_per_terms")]

    @property
    def is_valid(self):
        return self.status == self.Status.ACCEPTED


class OnboardingConflictReview(models.Model):
    class Reason(models.TextChoices):
        PROBABLE_DUPLICATE = "probable_duplicate", _("Doublon probable")
        OWNERSHIP_CONFLICT = "ownership_conflict", _("Conflit d'ownership")

    class Status(models.TextChoices):
        OPEN = "open", _("À examiner")
        RESOLVED = "resolved", _("Résolu")

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="onboarding_conflicts")
    candidate_project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="onboarding_conflict_candidates")
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE)
    reason = models.CharField(max_length=32, choices=Reason.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    details = models.JSONField(default=dict, blank=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="resolved_onboarding_conflicts")
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("status", "-detected_at")
        constraints = [
            models.UniqueConstraint(fields=("project", "candidate_project", "reason"), name="unique_onboarding_conflict_review")
        ]


class ProjectStatusHistory(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="status_history", verbose_name="projet"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="project_status_changes",
        verbose_name="acteur",
    )
    previous_status = models.CharField(
        "ancien statut", max_length=16, choices=Project.Status.choices
    )
    new_status = models.CharField("nouveau statut", max_length=16, choices=Project.Status.choices)
    created_at = models.DateTimeField("modifié le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "historique de statut projet"
        verbose_name_plural = "historiques de statut projet"

    def __str__(self):
        return f"{self.project} : {self.previous_status} → {self.new_status}"


@receiver(post_save, sender=Project)
def ensure_responsible_engineer_membership(sender, instance, **kwargs):
    """Keep the legacy responsible-engineer field aligned with contextual access."""
    if instance.engineer_id is None:
        return
    ProjectMembership.objects.update_or_create(
        project=instance,
        user_id=instance.engineer_id,
        defaults={
            "organization_id": instance.organization_id,
            "project_role": ProjectMembership.Role.ENGINEER,
        },
    )


@receiver(post_save, sender=ProjectOnboarding)
def ensure_initial_terms_version(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        owner = instance.project.ownership.owner
    except ProjectOwnership.DoesNotExist:
        owner = None
    ProjectTermsVersion.objects.get_or_create(
        project=instance.project,
        version=1,
        defaults={
            "organization": instance.organization,
            "budget_amount": instance.project.budget_amount,
            "currency": "XAF",
            "financial_conditions": instance.financial_conditions,
            "authority_owner": owner,
            "created_by": instance.initiated_by,
            "is_current": True,
        },
    )
    _flag_probable_onboarding_conflicts(instance.project, owner=owner)


@receiver(post_save, sender=ProjectOwnership)
def flag_ownership_conflicts(sender, instance, **kwargs):
    if hasattr(instance.project, "onboarding"):
        _flag_probable_onboarding_conflicts(instance.project, owner=instance.owner)


def _flag_probable_onboarding_conflicts(project, owner=None):
    candidates = Project.objects.filter(
        organization_id=project.organization_id,
        name__iexact=project.name,
        location__iexact=project.location,
        project_date=project.project_date,
    ).exclude(pk=project.pk)
    for candidate in candidates:
        reason = OnboardingConflictReview.Reason.PROBABLE_DUPLICATE
        if owner and ProjectOwnership.objects.filter(project=candidate, owner=owner).exists():
            reason = OnboardingConflictReview.Reason.OWNERSHIP_CONFLICT
        review, created = OnboardingConflictReview.objects.get_or_create(
            project=project, candidate_project=candidate, reason=reason,
            defaults={
                "organization_id": project.organization_id,
                "details": {
                    "matched_fields": ["name", "location", "project_date"],
                    "automatic_merge": False,
                },
            },
        )
        if created:
            from apps.audit.models import AuditEvent
            AuditEvent.objects.create(
                organization_id=project.organization_id,
                actor=project.onboarding.initiated_by,
                action="project.onboarding_conflict_detected",
                target_type="project", target_id=str(project.pk),
                metadata={"candidate_project_id": str(candidate.pk), "reason": reason},
            )


class ProjectDispute(models.Model):
    class TargetType(models.TextChoices):
        DOCUMENT = "document", _("Document")
        EXPENSE_REQUEST = "expense_request", _("Demande de dépense")
        EVIDENCE = "evidence", _("Preuve")
        INVENTORY_ANOMALY = "inventory_anomaly", _("Anomalie de stock")

    class Status(models.TextChoices):
        OPEN = "open", _("Ouverte")
        RESOLVED = "resolved", _("Résolue")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="project_disputes"
    )
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="disputes")
    target_type = models.CharField(max_length=32, choices=TargetType.choices)
    target_id = models.UUIDField()
    subject = models.CharField(max_length=200)
    reason = models.TextField(max_length=3000)
    freezes_decision = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="raised_project_disputes"
    )
    resolution = models.TextField(max_length=3000, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="resolved_project_disputes",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("status", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("project", "target_type", "target_id"),
                condition=models.Q(status="open"), name="one_open_dispute_per_project_target",
            )
        ]

    def clean(self):
        super().clean()
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError(_("La contestation doit appartenir à l’organisation du projet."))
        if not self.reason.strip():
            raise ValidationError({"reason": "Le motif de contestation est obligatoire."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ProjectDisputeObservation(models.Model):
    class Position(models.TextChoices):
        CLAIMANT = "claimant", _("Demandeur")
        RESPONDENT = "respondent", _("Partie contradictoire")
        PIVOT = "pivot", _("PIVOT")

    dispute = models.ForeignKey(ProjectDispute, on_delete=models.PROTECT, related_name="observations")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_dispute_observations"
    )
    position = models.CharField(max_length=16, choices=Position.choices)
    body = models.TextField(max_length=3000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)


class ProjectDisputeEvidence(models.Model):
    dispute = models.ForeignKey(ProjectDispute, on_delete=models.PROTECT, related_name="evidence_links")
    evidence = models.ForeignKey(
        "collaboration.EvidenceRecord", on_delete=models.PROTECT,
        related_name="dispute_links",
    )
    attached_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("dispute", "evidence"), name="unique_dispute_evidence")
        ]
