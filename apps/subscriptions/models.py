import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class SubscriptionPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(_("nom"), max_length=100)
    code = models.SlugField(_("code"), max_length=60, unique=True)
    description = models.CharField(_("description"), max_length=300, blank=True)
    monthly_price = models.DecimalField(
        _("prix mensuel"),
        max_digits=14,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    yearly_price = models.DecimalField(
        _("prix annuel"),
        max_digits=14,
        decimal_places=0,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(_("devise"), max_length=3, default="XAF")
    max_active_projects = models.PositiveIntegerField(
        _("projets actifs maximum"), null=True, blank=True
    )
    max_internal_members = models.PositiveIntegerField(
        _("membres internes maximum"), null=True, blank=True
    )
    storage_limit_mb = models.PositiveIntegerField(
        _("stockage maximum (Mo)"), null=True, blank=True
    )
    advanced_reports_enabled = models.BooleanField(_("rapports avancés"), default=False)
    ai_assistant_enabled = models.BooleanField(_("assistant IA"), default=False)
    features = models.JSONField(_("fonctionnalités"), default=dict, blank=True)
    is_active = models.BooleanField(_("actif"), default=True)
    is_public = models.BooleanField(_("visible dans le pricing"), default=True)
    display_order = models.PositiveSmallIntegerField(_("ordre d’affichage"), default=0)
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        ordering = ("display_order", "monthly_price", "name")
        verbose_name = _("forfait")
        verbose_name_plural = _("forfaits")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monthly_price__gte=0),
                name="subscription_plan_monthly_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(yearly_price__gte=0),
                name="subscription_plan_yearly_price_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(max_active_projects__isnull=True)
                | models.Q(max_active_projects__gt=0),
                name="subscription_plan_project_limit_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_internal_members__isnull=True)
                | models.Q(max_internal_members__gt=0),
                name="subscription_plan_member_limit_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(storage_limit_mb__isnull=True)
                | models.Q(storage_limit_mb__gt=0),
                name="subscription_plan_storage_limit_positive",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def snapshot(self) -> dict:
        return {
            "id": str(self.pk),
            "code": self.code,
            "name": self.name,
            "monthly_price": str(self.monthly_price),
            "yearly_price": str(self.yearly_price),
            "currency": self.currency,
            "max_active_projects": self.max_active_projects,
            "max_internal_members": self.max_internal_members,
            "storage_limit_mb": self.storage_limit_mb,
            "advanced_reports_enabled": self.advanced_reports_enabled,
            "ai_assistant_enabled": self.ai_assistant_enabled,
            "features": self.features,
        }


class OrganizationSubscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "trial", _("Essai")
        ACTIVE = "active", _("Actif")
        GRACE = "grace", _("Période de grâce")
        READ_ONLY = "read_only", _("Lecture seule")
        SUSPENDED = "suspended", _("Suspendu")
        CANCELLED = "cancelled", _("Annulé")
        EXPIRED = "expired", _("Expiré")

    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", _("Mensuel")
        YEARLY = "yearly", _("Annuel")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="subscription",
        verbose_name=_("organisation"),
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
        verbose_name=_("forfait"),
    )
    status = models.CharField(
        _("statut"), max_length=16, choices=Status.choices, default=Status.TRIAL
    )
    billing_cycle = models.CharField(
        _("périodicité"),
        max_length=10,
        choices=BillingCycle.choices,
        default=BillingCycle.MONTHLY,
    )
    trial_started_at = models.DateTimeField(_("début de l’essai"), null=True, blank=True)
    trial_ends_at = models.DateTimeField(_("fin de l’essai"), null=True, blank=True)
    current_period_started_at = models.DateTimeField(
        _("début de la période"), null=True, blank=True
    )
    current_period_ends_at = models.DateTimeField(
        _("fin de la période"), null=True, blank=True
    )
    grace_ends_at = models.DateTimeField(_("fin de la grâce"), null=True, blank=True)
    cancelled_at = models.DateTimeField(_("annulé le"), null=True, blank=True)
    pending_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, null=True, blank=True,
        related_name="scheduled_subscriptions",
    )
    pending_billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, blank=True
    )
    pending_effective_at = models.DateTimeField(null=True, blank=True)
    pending_period_ends_at = models.DateTimeField(null=True, blank=True)
    plan_snapshot = models.JSONField(_("instantané du forfait"), default=dict, blank=True)
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True)
    updated_at = models.DateTimeField(_("modifié le"), auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = _("abonnement d’organisation")
        verbose_name_plural = _("abonnements d’organisation")
        indexes = [
            models.Index(fields=("status", "current_period_ends_at")),
            models.Index(fields=("status", "trial_ends_at")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(trial_started_at__isnull=True)
                | models.Q(trial_ends_at__isnull=True)
                | models.Q(trial_ends_at__gt=models.F("trial_started_at")),
                name="subscription_trial_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(current_period_started_at__isnull=True)
                | models.Q(current_period_ends_at__isnull=True)
                | models.Q(current_period_ends_at__gt=models.F("current_period_started_at")),
                name="subscription_period_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(grace_ends_at__isnull=True)
                | models.Q(current_period_ends_at__isnull=True)
                | models.Q(grace_ends_at__gte=models.F("current_period_ends_at")),
                name="subscription_grace_after_period_end",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.TRIAL and (
            not self.trial_started_at or not self.trial_ends_at
        ):
            errors["trial_ends_at"] = _("Un abonnement d’essai exige ses dates de début et de fin.")
        if self.status in {self.Status.ACTIVE, self.Status.GRACE, self.Status.READ_ONLY} and (
            not self.current_period_started_at or not self.current_period_ends_at
        ):
            errors["current_period_ends_at"] = _(
                "Ce statut exige une période d’abonnement complète."
            )
        if self.status == self.Status.GRACE and not self.grace_ends_at:
            errors["grace_ends_at"] = _("La période de grâce exige une date de fin.")
        if self.status == self.Status.CANCELLED and not self.cancelled_at:
            errors["cancelled_at"] = _("Un abonnement annulé exige une date d’annulation.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.plan_snapshot and self.plan_id:
            self.plan_snapshot = self.plan.snapshot()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.organization} · {self.plan} · {self.get_status_display()}"


class SubscriptionPayment(models.Model):
    class Action(models.TextChoices):
        RENEWAL = "renewal", _("Renouvellement")
        UPGRADE = "upgrade", _("Montée de gamme")
        DOWNGRADE = "downgrade", _("Baisse programmée")

    class Status(models.TextChoices):
        INITIATED = "initiated", _("Initié")
        PENDING = "pending", _("En attente")
        SUCCESS = "success", _("Réussi")
        REFUSED = "refused", _("Refusé")
        CANCELLED = "cancelled", _("Annulé")
        FAILED = "failed", _("Échoué")
        EXPIRED = "expired", _("Expiré")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="subscription_payments"
    )
    subscription = models.ForeignKey(
        OrganizationSubscription, on_delete=models.PROTECT, related_name="payments"
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    billing_cycle = models.CharField(max_length=10, choices=OrganizationSubscription.BillingCycle.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=0, validators=[MinValueValidator(1)])
    currency = models.CharField(max_length=3, default="XAF")
    operator = models.CharField(max_length=30)
    payer_phone = models.CharField(max_length=20)
    provider = models.CharField(max_length=30, default="mesomb")
    provider_reference = models.CharField(max_length=100, blank=True)
    receipt_reference = models.CharField(max_length=64, unique=True, null=True, blank=True)
    idempotency_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INITIATED)
    action = models.CharField(max_length=16, choices=Action.choices, default=Action.RENEWAL)
    plan_snapshot = models.JSONField(default=dict)
    response_summary = models.JSONField(default=dict, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-requested_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("organization",),
                condition=models.Q(status__in=("initiated", "pending")),
                name="one_uncertain_subscription_payment_per_org",
            )
        ]


class SubscriptionEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(
        OrganizationSubscription,
        on_delete=models.PROTECT,
        related_name="events",
        verbose_name=_("abonnement"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscription_events",
        null=True,
        blank=True,
        verbose_name=_("acteur"),
    )
    event_type = models.CharField(_("type d’événement"), max_length=80)
    previous_status = models.CharField(
        _("ancien statut"),
        max_length=16,
        choices=OrganizationSubscription.Status.choices,
        blank=True,
    )
    new_status = models.CharField(
        _("nouveau statut"), max_length=16, choices=OrganizationSubscription.Status.choices
    )
    plan_snapshot = models.JSONField(_("instantané du forfait"), default=dict)
    metadata = models.JSONField(_("métadonnées"), default=dict, blank=True)
    occurred_at = models.DateTimeField(_("survenu le"), auto_now_add=True)

    class Meta:
        ordering = ("-occurred_at",)
        verbose_name = _("événement d’abonnement")
        verbose_name_plural = _("événements d’abonnement")
        indexes = [models.Index(fields=("subscription", "-occurred_at"))]

    def save(self, *args, **kwargs):
        if not self.plan_snapshot and self.subscription_id:
            self.plan_snapshot = (
                self.subscription.plan_snapshot or self.subscription.plan.snapshot()
            )
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.event_type} · {self.subscription.organization}"


class SubscriptionNoticeDelivery(models.Model):
    class Channel(models.TextChoices):
        IN_APP = "in_app", _("Dans l’application")
        EMAIL = "email", _("E-mail")

    subscription = models.ForeignKey(
        OrganizationSubscription, on_delete=models.CASCADE, related_name="notice_deliveries"
    )
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    milestone = models.CharField(max_length=40)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "recipient", "milestone", "channel"),
                name="unique_subscription_notice_delivery",
            )
        ]
