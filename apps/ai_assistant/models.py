from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone


def conversation_expiration():
    return timezone.now() + timedelta(days=settings.AI_CONVERSATION_RETENTION_DAYS)


class AssistantConversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archivée"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="assistant_conversations",
        null=True,
        blank=True,
        verbose_name="organisation",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_conversations",
        verbose_name="utilisateur",
    )
    title = models.CharField("titre", max_length=120, default="Nouvelle conversation")
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)
    archived_at = models.DateTimeField("archivée le", null=True, blank=True)
    expires_at = models.DateTimeField("expire le", default=conversation_expiration, db_index=True)

    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "conversation avec l’assistant"
        verbose_name_plural = "conversations avec l’assistant"
        indexes = [models.Index(fields=("user", "status", "-updated_at"))]

    def clean(self):
        super().clean()
        if self.user_id and self.organization_id != self.user.organization_id:
            raise ValidationError(
                {"organization": "La conversation doit appartenir à l’organisation du compte."}
            )
        if self.status == self.Status.ARCHIVED and self.archived_at is None:
            raise ValidationError({"archived_at": "Une conversation archivée doit être horodatée."})

    def __str__(self):
        return f"{self.user.get_username()} · {self.title}"


class AssistantMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Utilisateur"
        ASSISTANT = "assistant", "Assistant"

    class Status(models.TextChoices):
        PENDING = "pending", "En attente"
        COMPLETED = "completed", "Terminé"
        FAILED = "failed", "Échec"

    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="conversation",
    )
    role = models.CharField("rôle", max_length=16, choices=Role.choices)
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.COMPLETED
    )
    content = models.TextField(
        "contenu", validators=[MaxLengthValidator(settings.AI_MESSAGE_MAX_CHARS)]
    )
    error_code = models.CharField("code d’erreur", max_length=64, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "message de l’assistant"
        verbose_name_plural = "messages de l’assistant"
        indexes = [models.Index(fields=("conversation", "created_at"))]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status="failed", error_code__gt="") | ~models.Q(status="failed"),
                name="assistant_failed_message_has_error_code",
            )
        ]

    def clean(self):
        super().clean()
        if self.status == self.Status.FAILED and not self.error_code:
            raise ValidationError({"error_code": "Un message en échec doit avoir un code."})
        if self.status != self.Status.FAILED and self.error_code:
            raise ValidationError({"error_code": "Ce message ne doit pas avoir de code d’erreur."})

    def __str__(self):
        return f"{self.get_role_display()} · conversation #{self.conversation_id}"


class AssistantRequest(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "En cours"
        SUCCESS = "success", "Réussie"
        FAILED = "failed", "Échec"
        BLOCKED = "blocked", "Bloquée"

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="assistant_requests",
        null=True,
        blank=True,
        verbose_name="organisation",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_requests",
        verbose_name="utilisateur",
    )
    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name="requests",
        verbose_name="conversation",
    )
    request_hash = models.CharField("empreinte de requête", max_length=64)
    status = models.CharField(
        "statut", max_length=16, choices=Status.choices, default=Status.PROCESSING
    )
    prompt_tokens = models.PositiveIntegerField(null=True, blank=True)
    completion_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField("code d’erreur", max_length=64, blank=True)
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    completed_at = models.DateTimeField("terminée le", null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "requête vers l’assistant"
        verbose_name_plural = "requêtes vers l’assistant"
        indexes = [
            models.Index(
                fields=("user", "-created_at"),
                name="ai_assistan_user_id_50cff1_idx",
            ),
            models.Index(
                fields=("request_hash", "-created_at"),
                name="ai_assistan_request_d97ae5_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(status="processing"),
                name="one_processing_assistant_request_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user.get_username()} · {self.status}"
