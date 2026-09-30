from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    class Role(models.TextChoices):
        ENGINEER = "engineer", _("Ingénieur")
        CLIENT = "client", _("Client")
        CONTRACTOR = "contractor", _("Entrepreneur")
        SITE_MANAGER = "site_manager", _("Responsable de chantier")
        ADMIN = "admin", _("Administrateur")

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="organisation",
    )
    role = models.CharField(
        "rôle",
        max_length=20,
        choices=Role.choices,
        default=Role.CLIENT,
    )

    class Meta(AbstractUser.Meta):
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(organization__isnull=False) | models.Q(is_superuser=True),
                name="account_business_user_has_organization",
            )
        ]


def invitation_expiration():
    return timezone.now() + timedelta(days=7)


class InvitationQuerySet(models.QuerySet):
    def active(self):
        return self.filter(
            accepted_at__isnull=True,
            canceled_at__isnull=True,
            expires_at__gt=timezone.now(),
        )

    def closed(self):
        return self.filter(
            models.Q(accepted_at__isnull=False)
            | models.Q(canceled_at__isnull=False)
            | models.Q(
                accepted_at__isnull=True,
                canceled_at__isnull=True,
                expires_at__lte=timezone.now(),
            )
        )


class Invitation(models.Model):
    class State(models.TextChoices):
        PENDING = "pending", _("En attente")
        ACCEPTED = "accepted", _("Acceptée")
        CANCELLED = "cancelled", _("Annulée")
        EXPIRED = "expired", _("Expirée")

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name="organisation",
    )
    invited_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="sent_invitations",
        verbose_name="invité par",
    )
    email = models.EmailField("adresse e-mail")
    role = models.CharField(
        "rôle",
        max_length=20,
        choices=(
            (User.Role.CLIENT, User.Role.CLIENT.label),
            (User.Role.CONTRACTOR, User.Role.CONTRACTOR.label),
            (User.Role.SITE_MANAGER, User.Role.SITE_MANAGER.label),
            (User.Role.ENGINEER, User.Role.ENGINEER.label),
        ),
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="actor_invitations",
        null=True,
        blank=True,
        verbose_name="projet",
    )
    project_role = models.CharField(
        "rôle projet", max_length=24, blank=True,
        choices=(
            ("owner", _("Propriétaire")),
            ("contractor", _("Entrepreneur")),
            ("site_manager", _("Responsable de chantier")),
            ("engineer", _("Ingénieur")),
        ),
    )
    token_hash = models.CharField("empreinte du jeton", max_length=64, unique=True)
    expires_at = models.DateTimeField("expire le", default=invitation_expiration)
    accepted_at = models.DateTimeField("acceptée le", null=True, blank=True)
    canceled_at = models.DateTimeField("annulée le", null=True, blank=True)
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    objects = InvitationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "invitation"
        verbose_name_plural = "invitations"
        indexes = [models.Index(fields=("organization", "email"))]

    @property
    def is_usable(self) -> bool:
        return (
            self.accepted_at is None
            and self.canceled_at is None
            and self.expires_at > timezone.now()
        )

    @property
    def state(self) -> str:
        if self.accepted_at is not None:
            return self.State.ACCEPTED
        if self.canceled_at is not None:
            return self.State.CANCELLED
        if self.expires_at <= timezone.now():
            return self.State.EXPIRED
        return self.State.PENDING

    @property
    def state_label(self) -> str:
        return self.State(self.state).label

    def __str__(self) -> str:
        return f"{self.email} · {self.get_role_display()}"


def validate_avatar_size(file):
    max_size = 3 * 1024 * 1024
    if file.size > max_size:
        raise ValidationError(_("La photo ne doit pas dépasser 3 Mo."))


def profile_avatar_path(instance, filename):
    extension = Path(filename).suffix.lower() or ".jpg"
    return f"profiles/{instance.user.organization_id}/{instance.user_id}/avatar{extension}"


class UserProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="utilisateur",
    )
    phone = models.CharField("téléphone", max_length=30, blank=True)
    location = models.CharField("localisation", max_length=160, blank=True)
    bio = models.TextField("biographie", max_length=600, blank=True)
    avatar = models.ImageField(
        "photo de profil",
        upload_to=profile_avatar_path,
        validators=[validate_avatar_size],
        blank=True,
    )
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "profil utilisateur"
        verbose_name_plural = "profils utilisateurs"

    def __str__(self) -> str:
        return f"Profil de {self.user.username}"


class Notification(models.Model):
    class Kind(models.TextChoices):
        PROJECT = "project", _("Projet")
        DOCUMENT = "document", _("Document")
        FINANCE = "finance", _("Finance")
        ACCOUNT = "account", _("Compte")

    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="triggered_notifications",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=160)
    message = models.CharField(max_length=500, blank=True)
    target_url = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("recipient", "is_read", "created_at"),
                name="account_notif_recipient_idx",
            ),
            models.Index(fields=("organization", "created_at"), name="account_notif_org_idx"),
        ]

    def __str__(self):
        return f"{self.recipient} · {self.title}"
