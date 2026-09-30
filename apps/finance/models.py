import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError


def payment_reference():
    return f"PIVOT-{uuid.uuid4()}"


class ExpenseRequest(models.Model):
    class Type(models.TextChoices):
        MATERIAL = "material", _("Matériaux")
        LABOR = "labor", _("Main-d’œuvre")
        SERVICE = "service", _("Prestation")
        EQUIPMENT = "equipment", _("Équipement")
        OTHER = "other", _("Autre")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        SUBMITTED = "submitted", _("Soumise")
        EVIDENCE = "evidence", _("En preuve")
        REVIEW = "review", _("En revue")
        VERIFIED = "verified", _("Vérifiée")
        AUTHORIZED = "authorized", _("Autorisée")
        REJECTED = "rejected", _("Refusée")
        CLOSED = "closed", _("Close")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="expense_requests")
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="expense_requests")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="authored_expense_requests")
    milestone = models.ForeignKey("planning.ProjectStage", on_delete=models.PROTECT, related_name="expense_requests")
    expense_type = models.CharField(max_length=16, choices=Type.choices, default=Type.OTHER)
    amount = models.DecimalField(max_digits=16, decimal_places=0, validators=[MinValueValidator(1)])
    currency = models.CharField(max_length=3, default="XAF")
    purpose = models.CharField(max_length=500)
    beneficiary = models.CharField(max_length=200)
    due_date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    status_version = models.PositiveIntegerField(default=1)
    risk_score = models.PositiveSmallIntegerField(default=0)
    risk_level = models.CharField(max_length=12, default="low")
    pivot_review_required = models.BooleanField(default=False)
    risk_reasons = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "project", "status"))]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_request_amount_positive")]

    def clean(self):
        super().clean()
        if self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError(_("La demande doit appartenir à l’organisation du projet."))
        if self.author_id and not self.author.is_superuser:
            from apps.projects.models import ProjectMembership

            if not ProjectMembership.objects.filter(
                project_id=self.project_id,
                user_id=self.author_id,
                project_role=ProjectMembership.Role.CONTRACTOR,
            ).exists():
                raise ValidationError(_("L’auteur doit être un entrepreneur affecté au projet."))
        if self.project_id and self.milestone_id and (self.milestone.project_id != self.project_id or self.milestone.organization_id != self.organization_id):
            raise ValidationError(_("Le jalon doit appartenir au même projet."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExpenseRequestTransition(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(ExpenseRequest, on_delete=models.PROTECT, related_name="transitions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="expense_request_transitions")
    previous_status = models.CharField(max_length=16, choices=ExpenseRequest.Status.choices)
    new_status = models.CharField(max_length=16, choices=ExpenseRequest.Status.choices)
    reason = models.CharField(max_length=500, blank=True)
    status_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [models.UniqueConstraint(fields=("request", "status_version"), name="unique_expense_status_version")]


class ExpenseRequestAttachment(models.Model):
    class DocumentType(models.TextChoices):
        INVOICE = "invoice", _("Facture")
        QUOTE = "quote", _("Devis")
        DELIVERY_NOTE = "delivery_note", _("Bon de livraison")
        FIELD_EVIDENCE = "field_evidence", _("Preuve terrain")
        WORK_EVIDENCE = "work_evidence", _("Travaux réalisés")
        PROGRESS_EVIDENCE = "progress_evidence", _("Progression du chantier")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        REJECTED = "rejected", _("Rejetée")
        REPLACED = "replaced", _("Remplacée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT, related_name="expense_attachments")
    request = models.ForeignKey(ExpenseRequest, on_delete=models.PROTECT, related_name="attachments")
    evidence = models.ForeignKey("collaboration.EvidenceRecord", on_delete=models.PROTECT, related_name="expense_attachments")
    document_type = models.CharField(max_length=24, choices=DocumentType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="added_expense_attachments")
    reason = models.CharField(max_length=500, blank=True)
    replaced_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="replaces")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at",)
        indexes = [models.Index(fields=("request", "document_type", "status"))]
        constraints = [
            models.UniqueConstraint(
                fields=("request", "evidence"),
                condition=models.Q(status="active"),
                name="unique_active_expense_evidence",
            )
        ]

    def clean(self):
        super().clean()
        if self.request_id and self.request.organization_id != self.organization_id:
            raise ValidationError(_("La pièce doit appartenir à l’organisation de la demande."))
        if self.evidence_id and self.request_id and (self.evidence.project_id != self.request.project_id or self.evidence.organization_id != self.organization_id):
            raise ValidationError(_("La preuve doit appartenir au même projet."))
        if self.replaced_by_id and self.replaced_by.request_id != self.request_id:
            raise ValidationError(_("La pièce de remplacement doit appartenir à la même demande."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExpenseTechnicalOpinion(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", _("Approuvé")
        CONDITIONAL = "conditional", _("Conditionnel")
        REJECTED = "rejected", _("Rejeté")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="expense_technical_opinions",
    )
    request = models.ForeignKey(
        ExpenseRequest, on_delete=models.PROTECT, related_name="technical_opinions"
    )
    engineer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="expense_technical_opinions",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=1000)
    reviewed_status_version = models.PositiveIntegerField()
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("request",), condition=models.Q(is_current=True),
                name="one_current_expense_technical_opinion",
            ),
            models.UniqueConstraint(
                fields=("request", "reviewed_status_version"),
                name="unique_expense_opinion_reviewed_version",
            ),
        ]

    def clean(self):
        super().clean()
        if self.request_id and self.request.organization_id != self.organization_id:
            raise ValidationError(_("L’avis doit appartenir à l’organisation de la demande."))
        if self.engineer_id and not self.engineer.is_superuser:
            from apps.projects.models import ProjectMembership

            if not ProjectMembership.objects.filter(
                project_id=self.request.project_id,
                user_id=self.engineer_id,
                project_role=ProjectMembership.Role.ENGINEER,
            ).exists():
                raise ValidationError(_("L’ingénieur doit être affecté à ce projet."))
        if not self.reason.strip():
            raise ValidationError({"reason": "Le motif de l’avis technique est obligatoire."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExpensePivotVerification(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", _("Approuvée")
        REJECTED = "rejected", _("Rejetée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="expense_pivot_verifications",
    )
    request = models.ForeignKey(
        ExpenseRequest, on_delete=models.PROTECT, related_name="pivot_verifications"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="expense_pivot_verifications",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=1000)
    reviewed_status_version = models.PositiveIntegerField()
    risk_score_snapshot = models.PositiveSmallIntegerField()
    risk_reasons_snapshot = models.JSONField(default=list)
    is_exceptional = models.BooleanField(default=False)
    confirmation = models.CharField(max_length=100, blank=True)
    is_current = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("request",), condition=models.Q(is_current=True),
                name="one_current_expense_pivot_verification",
            ),
            models.UniqueConstraint(
                fields=("request", "reviewed_status_version"),
                name="unique_pivot_verification_request_version",
            ),
        ]

    def clean(self):
        super().clean()
        if self.request_id and self.request.organization_id != self.organization_id:
            raise ValidationError(_("La vérification doit appartenir à l’organisation de la demande."))
        if not self.reason.strip():
            raise ValidationError({"reason": "La motivation de la vérification est obligatoire."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExpenseOwnerDecision(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", _("Autorisée")
        REJECTED = "rejected", _("Refusée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="expense_owner_decisions",
    )
    request = models.ForeignKey(
        ExpenseRequest, on_delete=models.PROTECT, related_name="owner_decisions"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="expense_owner_decisions",
    )
    decision = models.CharField(max_length=16, choices=Decision.choices)
    reason = models.CharField(max_length=1000, blank=True)
    decided_status_version = models.PositiveIntegerField()
    resulting_status_version = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("request", "decided_status_version"),
                name="unique_owner_decision_request_version",
            )
        ]

    def clean(self):
        super().clean()
        if self.request_id and self.request.organization_id != self.organization_id:
            raise ValidationError(_("La décision doit appartenir à l’organisation de la demande."))
        if self.decision == self.Decision.REJECTED and not self.reason.strip():
            raise ValidationError({"reason": "Le motif du refus est obligatoire."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class PaymentTransaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        SUCCESS = "success", _("Réussi")
        FAILED = "failed", _("Échoué")
        CANCELLED = "cancelled", _("Annulé")
        EXPIRED = "expired", _("Expiré")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="payment_transactions"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    expense_request = models.ForeignKey(
        ExpenseRequest, on_delete=models.PROTECT, related_name="payment_transactions",
        null=True, blank=True,
    )
    owner_decision = models.ForeignKey(
        ExpenseOwnerDecision, on_delete=models.PROTECT, related_name="payment_transactions",
        null=True, blank=True,
    )
    amount = models.DecimalField(max_digits=16, decimal_places=0, validators=[MinValueValidator(1)])
    currency = models.CharField(max_length=3, default="XAF")
    beneficiary_snapshot = models.CharField(max_length=200, blank=True)
    provider = models.CharField(max_length=30, default="simulated")
    operator = models.CharField(max_length=30)
    payer_phone = models.CharField(max_length=20)
    pivot_reference = models.CharField(max_length=100, unique=True, default=payment_reference, editable=False)
    provider_reference = models.CharField(max_length=100, blank=True)
    operator_reference = models.CharField(max_length=100, blank=True)
    idempotency_key = models.UUIDField(unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    raw_response_redacted = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("project", "user"),
                condition=models.Q(status="pending"),
                name="one_pending_payment_per_user_project",
            ),
            models.UniqueConstraint(
                fields=("expense_request",),
                condition=models.Q(status="pending", expense_request__isnull=False),
                name="one_pending_payment_per_expense_request",
            ),
            models.UniqueConstraint(
                fields=("expense_request",),
                condition=models.Q(status="success", expense_request__isnull=False),
                name="one_success_payment_per_expense_request",
            ),
        ]


class Withdrawal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        ACCOUNTED = "accounted", _("Comptabilisé")
        REJECTED = "rejected", _("Rejeté")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("organizations.Organization", on_delete=models.PROTECT)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="withdrawals"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=0, validators=[MinValueValidator(1)])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField(max_length=500)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_withdrawals"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="decided_withdrawals",
        null=True,
        blank=True,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
