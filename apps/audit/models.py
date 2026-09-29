from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models


class AuditEvent(models.Model):
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="audit_events",
        null=True,
        blank=True,
        verbose_name="organisation",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="audit_events",
        verbose_name="acteur",
    )
    action = models.CharField("action", max_length=100)
    target_type = models.CharField("type de cible", max_length=100)
    target_id = models.CharField("identifiant de cible", max_length=100)
    metadata = models.JSONField("métadonnées", default=dict, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "événement d'audit"
        verbose_name_plural = "événements d'audit"

    def __str__(self) -> str:
        return f"{self.action} · {self.target_type}#{self.target_id}"


class PlatformConfiguration(models.Model):
    platform_name = models.CharField("nom de la plateforme", max_length=80, default="PIVOT")
    support_email = models.EmailField("e-mail de support", blank=True)
    engineer_registration_enabled = models.BooleanField("inscription ingénieur autorisée", default=True)
    client_registration_enabled = models.BooleanField("inscription client autorisée", default=True)
    platform_notice = models.CharField("message d’information", max_length=300, blank=True)
    notification_retention_days = models.PositiveSmallIntegerField(
        "rétention des notifications (jours)",
        default=90,
        validators=[MinValueValidator(7), MaxValueValidator(365)],
    )
    evidence_retention_days = models.PositiveSmallIntegerField(
        "rétention minimale des preuves (jours)", default=1825,
        validators=[MinValueValidator(90), MaxValueValidator(3650)],
    )
    evidence_download_requires_approval = models.BooleanField(
        "téléchargement des preuves après approbation uniquement", default=True
    )
    evidence_location_restricted = models.BooleanField(
        "coordonnées réservées au propriétaire et aux contrôleurs", default=True
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="platform_configuration_updates",
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "configuration de la plateforme"
        verbose_name_plural = "configuration de la plateforme"

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        configuration, _ = cls.objects.get_or_create(pk=1)
        return configuration

    def __str__(self):
        return self.platform_name


class PilotRecommendation(models.Model):
    class RespondentRole(models.TextChoices):
        CLIENT = "client", "Client"
        CONTRACTOR = "contractor", "Entrepreneur"

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT,
        related_name="pilot_recommendations",
    )
    respondent_role = models.CharField(max_length=16, choices=RespondentRole.choices)
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(10)]
    )
    note = models.CharField(max_length=1000, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="recorded_pilot_recommendations",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-recorded_at",)


class PilotPricingHypothesis(models.Model):
    class Status(models.TextChoices):
        TESTING = "testing", "En test"
        VALIDATED = "validated", "Validée"
        REJECTED = "rejected", "Rejetée"

    segment = models.CharField(max_length=120)
    plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan", on_delete=models.PROTECT,
        related_name="pilot_pricing_hypotheses",
    )
    proposed_monthly_price = models.DecimalField(
        max_digits=14, decimal_places=0, validators=[MinValueValidator(0)]
    )
    sample_size = models.PositiveIntegerField(default=0)
    positive_responses = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TESTING)
    assumptions = models.TextField(max_length=3000)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="recorded_pricing_hypotheses",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.positive_responses > self.sample_size:
            raise ValidationError({"positive_responses": "Les réponses positives ne peuvent pas dépasser l’échantillon."})
        if not self.assumptions.strip():
            raise ValidationError({"assumptions": "Les hypothèses doivent être documentées."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def positive_rate(self):
        return round(self.positive_responses * 100 / self.sample_size, 1) if self.sample_size else 0


class PilotReviewDecision(models.Model):
    class Horizon(models.IntegerChoices):
        DAYS_30 = 30, "30 jours"
        DAYS_60 = 60, "60 jours"
        DAYS_90 = 90, "90 jours"

    class Decision(models.TextChoices):
        GO = "go", "Go"
        CONDITIONAL_GO = "conditional_go", "Go conditionnel"
        NO_GO = "no_go", "No-go"

    horizon_days = models.PositiveSmallIntegerField(choices=Horizon.choices)
    as_of_date = models.DateField()
    decision = models.CharField(max_length=20, choices=Decision.choices)
    rationale = models.TextField(max_length=3000)
    product_decisions = models.TextField(max_length=5000)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="recorded_pilot_review_decisions",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-as_of_date", "-recorded_at")
        constraints = [
            models.UniqueConstraint(
                fields=("horizon_days", "as_of_date"),
                name="unique_pilot_review_horizon_date",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        if not self.rationale.strip():
            errors["rationale"] = "La justification de la décision est obligatoire."
        if not self.product_decisions.strip():
            errors["product_decisions"] = "Les décisions produit doivent être documentées."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
