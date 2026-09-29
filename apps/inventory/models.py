import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _


class StockItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente")
        VERIFIED = "verified", _("Vérifié")
        APPROVED = "approved", _("Approuvé")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="stock_items"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="stock_items"
    )
    name = models.CharField("nom", max_length=200)
    unit = models.CharField("unité", max_length=30)
    unit_price = models.DecimalField(
        "prix unitaire", max_digits=16, decimal_places=2, validators=[MinValueValidator(0)]
    )
    quantity = models.DecimalField(
        "quantité", max_digits=16, decimal_places=2, validators=[MinValueValidator(0)]
    )
    alert_threshold = models.DecimalField(
        "seuil d'alerte",
        max_digits=16,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_stock_items"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="verified_stock_items",
        null=True,
        blank=True,
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    expected_range = models.ForeignKey(
        "InventoryExpectedRange", on_delete=models.PROTECT, related_name="stock_items",
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0), name="stock_quantity_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="stock_price_non_negative"
            ),
        ]
        indexes = [models.Index(fields=("organization", "project", "status"))]

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    @property
    def is_low_stock(self):
        return self.quantity <= self.alert_threshold

    def movement_total(self, movement_type):
        return self.movements.filter(movement_type=movement_type).aggregate(
            total=Sum("normalized_quantity")
        )["total"] or 0

    @property
    def purchased_quantity(self):
        return self.movement_total(StockMovement.Type.PURCHASED)

    @property
    def delivered_quantity(self):
        return self.movement_total(StockMovement.Type.DELIVERED)

    @property
    def consumed_quantity(self):
        return self.movement_total(StockMovement.Type.CONSUMED)

    @property
    def derived_remaining_quantity(self):
        if not self.movements.exists():
            return self.quantity
        return self.movements.exclude(movement_type=StockMovement.Type.PURCHASED).aggregate(
            total=Sum("variation")
        )["total"] or 0

    @property
    def expected_range_advice(self):
        rule = self.expected_range
        if not rule:
            return None
        quantity = self.consumed_quantity
        if quantity < rule.minimum_quantity:
            return "below"
        if quantity > rule.maximum_quantity:
            return "above"
        return "within"

    def clean(self):
        super().clean()
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError("L'article doit appartenir à l'organisation du projet.")
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
                raise ValidationError("Le créateur doit pouvoir gérer le stock de ce projet.")

    def __str__(self):
        return f"{self.project} · {self.name}"


class StockMovement(models.Model):
    class Type(models.TextChoices):
        PURCHASED = "purchased", _("Acheté")
        DELIVERED = "delivered", _("Livré")
        CONSUMED = "consumed", _("Consommé")
        CORRECTION = "correction", _("Correction inventaire")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="stock_movements"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="stock_movements"
    )
    item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="movements")
    evidence = models.ForeignKey(
        "collaboration.EvidenceRecord", on_delete=models.PROTECT,
        related_name="stock_movements", null=True, blank=True,
    )
    stage = models.ForeignKey(
        "planning.ProjectStage", on_delete=models.PROTECT,
        related_name="stock_movements", null=True, blank=True,
    )
    movement_type = models.CharField(max_length=16, choices=Type.choices, default=Type.CORRECTION)
    source_reference = models.CharField("source", max_length=200, default="Stock d'ouverture")
    source_quantity = models.DecimalField("quantité source", max_digits=16, decimal_places=4, default=0)
    source_unit = models.CharField("unité source", max_length=30, default="unité")
    conversion_factor = models.DecimalField(
        "facteur de conversion", max_digits=16, decimal_places=6, default=1,
        validators=[MinValueValidator(0.000001)],
    )
    normalized_quantity = models.DecimalField(
        "quantité convertie", max_digits=16, decimal_places=4, default=0
    )
    variation = models.DecimalField("variation", max_digits=16, decimal_places=2)
    resulting_quantity = models.DecimalField("quantité résultante", max_digits=16, decimal_places=2)
    reason = models.CharField("motif", max_length=500)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="stock_movements"
    )
    idempotency_key = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("organization", "project", "-created_at"))]

    def clean(self):
        super().clean()
        if self.item_id and (
            self.project_id != self.item.project_id or self.organization_id != self.item.organization_id
        ):
            raise ValidationError("Le mouvement doit appartenir au projet et à l'organisation de l'article.")
        if self.evidence_id and (
            self.evidence.project_id != self.project_id
            or self.evidence.organization_id != self.organization_id
        ):
            raise ValidationError("La pièce justificative doit appartenir au même projet.")
        if self.stage_id and (
            self.stage.project_id != self.project_id
            or self.stage.organization_id != self.organization_id
        ):
            raise ValidationError("L'étape doit appartenir au même projet.")
        if self.evidence_id:
            expected = {
                self.Type.PURCHASED: "invoice",
                self.Type.DELIVERED: "delivery_note",
            }.get(self.movement_type)
            if expected and self.evidence.evidence_type != expected:
                raise ValidationError("La nature de la pièce ne correspond pas au mouvement.")
        if self.movement_type != self.Type.CORRECTION and self.source_quantity < 0:
            raise ValidationError({"source_quantity": "La quantité source doit être positive."})
        if self.normalized_quantity != abs(self.source_quantity * self.conversion_factor):
            raise ValidationError("La quantité convertie ne correspond pas à la conversion déclarée.")

    def __str__(self):
        return f"{self.item} · {self.variation:+}"


class InventoryExpectedRange(models.Model):
    class OutOfRangeAction(models.TextChoices):
        FLAG = "flag", _("Signaler sans bloquer")
        BLOCK = "block", _("Bloquer avant paiement")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="inventory_expected_ranges",
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="inventory_expected_ranges"
    )
    work_type = models.CharField("ouvrage", max_length=200)
    unit = models.CharField("unité", max_length=30)
    minimum_quantity = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(0)])
    maximum_quantity = models.DecimalField(max_digits=16, decimal_places=4, validators=[MinValueValidator(0)])
    assumptions = models.TextField("hypothèses", max_length=3000)
    out_of_range_action = models.CharField(
        max_length=10, choices=OutOfRangeAction.choices, default=OutOfRangeAction.FLAG
    )
    version = models.PositiveIntegerField()
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, related_name="newer_versions", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_inventory_expected_ranges",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("work_type", "-version")
        constraints = [models.UniqueConstraint(
            fields=("project", "work_type", "unit", "version"),
            name="unique_inventory_expected_range_version",
        )]

    def clean(self):
        super().clean()
        if self.project_id and self.project.organization_id != self.organization_id:
            raise ValidationError("La plage doit appartenir à l'organisation du projet.")
        if self.minimum_quantity > self.maximum_quantity:
            raise ValidationError("La borne minimale ne peut pas dépasser la borne maximale.")
        if not self.assumptions.strip():
            raise ValidationError({"assumptions": "Les hypothèses techniques sont obligatoires."})
        if self.supersedes_id and (
            self.supersedes.project_id != self.project_id
            or self.supersedes.work_type != self.work_type
            or self.supersedes.unit != self.unit
            or self.version != self.supersedes.version + 1
        ):
            raise ValidationError("La version précédente doit concerner le même ouvrage et la même unité.")

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            immutable = (
                "organization_id", "project_id", "work_type", "unit",
                "minimum_quantity", "maximum_quantity", "assumptions",
                "out_of_range_action", "version", "supersedes_id", "created_by_id",
            )
            if original and any(getattr(original, field) != getattr(self, field) for field in immutable):
                raise ValidationError("Une plage publiée est immuable ; créez une nouvelle version.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.work_type} · {self.minimum_quantity}–{self.maximum_quantity} {self.unit} · v{self.version}"


class InventoryAnomaly(models.Model):
    class Direction(models.TextChoices):
        BELOW = "below", _("Sous la plage")
        ABOVE = "above", _("Au-dessus de la plage")

    class Status(models.TextChoices):
        OPEN = "open", _("Ouverte")
        RESOLVED = "resolved", _("Résolue")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="inventory_anomalies"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="inventory_anomalies"
    )
    expense_request = models.ForeignKey(
        "finance.ExpenseRequest", on_delete=models.PROTECT, related_name="inventory_anomalies"
    )
    item = models.ForeignKey(StockItem, on_delete=models.PROTECT, related_name="anomalies")
    expected_range = models.ForeignKey(
        InventoryExpectedRange, on_delete=models.PROTECT, related_name="anomalies"
    )
    expected_range_version = models.PositiveIntegerField()
    minimum_snapshot = models.DecimalField(max_digits=16, decimal_places=4)
    maximum_snapshot = models.DecimalField(max_digits=16, decimal_places=4)
    observed_quantity = models.DecimalField(max_digits=16, decimal_places=4)
    unit_snapshot = models.CharField(max_length=30)
    direction = models.CharField(max_length=10, choices=Direction.choices)
    action = models.CharField(max_length=10, choices=InventoryExpectedRange.OutOfRangeAction.choices)
    movement_ids = models.JSONField(default=list)
    fingerprint = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    detected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-detected_at",)
        indexes = [models.Index(fields=("project", "status", "-detected_at"))]

    @property
    def blocks_payment(self):
        return self.status == self.Status.OPEN and self.action == InventoryExpectedRange.OutOfRangeAction.BLOCK

    def clean(self):
        super().clean()
        if self.project_id and self.organization_id != self.project.organization_id:
            raise ValidationError("L'anomalie doit appartenir à l'organisation du projet.")
        if self.expense_request_id and self.expense_request.project_id != self.project_id:
            raise ValidationError("La demande de dépense doit appartenir au même projet.")
        if self.item_id and self.item.project_id != self.project_id:
            raise ValidationError("L'article doit appartenir au même projet.")
        if self.expected_range_id and self.expected_range.project_id != self.project_id:
            raise ValidationError("La plage attendue doit appartenir au même projet.")

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            protected = (
                "organization_id", "project_id", "expense_request_id", "item_id",
                "expected_range_id", "expected_range_version", "minimum_snapshot",
                "maximum_snapshot", "observed_quantity", "unit_snapshot", "direction",
                "action", "movement_ids", "fingerprint",
            )
            if original and any(getattr(original, field) != getattr(self, field) for field in protected):
                raise ValidationError("Le constat d'une anomalie est immuable.")
        self.full_clean()
        return super().save(*args, **kwargs)


class InventoryAnomalyResolution(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("En attente de validation")
        APPROVED = "approved", _("Validée")
        REJECTED = "rejected", _("Rejetée")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anomaly = models.ForeignKey(
        InventoryAnomaly, on_delete=models.PROTECT, related_name="resolutions"
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="responsible_inventory_anomaly_resolutions",
    )
    evidence = models.ManyToManyField(
        "collaboration.EvidenceRecord", related_name="inventory_anomaly_resolutions"
    )
    reason = models.TextField(max_length=3000)
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="proposed_inventory_anomaly_resolutions",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="decided_inventory_anomaly_resolutions", null=True, blank=True,
    )
    decision_reason = models.TextField(max_length=3000, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("submitted_at",)
        constraints = [models.UniqueConstraint(
            fields=("anomaly",), condition=models.Q(status="pending"),
            name="one_pending_inventory_anomaly_resolution",
        )]

    def clean(self):
        super().clean()
        if self.responsible_id and self.anomaly_id:
            if not self.responsible.project_memberships.filter(project=self.anomaly.project).exists():
                raise ValidationError("Le responsable doit être membre du projet.")
        if not self.reason.strip():
            raise ValidationError({"reason": "Le motif de résolution est obligatoire."})
        if self.status != self.Status.PENDING and (not self.decided_by_id or not self.decision_reason.strip()):
            raise ValidationError("Une décision exige un validateur et un motif.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
