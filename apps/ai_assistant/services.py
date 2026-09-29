from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent

from .models import AssistantConversation, AssistantMessage


@transaction.atomic
def create_conversation(*, user, title="Nouvelle conversation"):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("Un compte actif est requis.")
    conversation = AssistantConversation(
        user=user,
        organization=user.organization,
        title=(title or "Nouvelle conversation").strip()[:120],
    )
    conversation.full_clean()
    conversation.save()
    return conversation


@transaction.atomic
def add_message(*, user, conversation, role, content, status=None, error_code=""):
    locked = AssistantConversation.objects.select_for_update().get(pk=conversation.pk)
    if locked.user_id != user.pk:
        raise PermissionDenied("Cette conversation ne vous appartient pas.")
    if locked.status != AssistantConversation.Status.ACTIVE:
        raise ValidationError("Cette conversation est archivée.")
    if locked.expires_at <= timezone.now():
        raise ValidationError("Cette conversation a expiré.")
    if locked.messages.count() >= settings.AI_CONVERSATION_MAX_MESSAGES:
        raise ValidationError("Cette conversation a atteint sa limite de messages.")
    normalized_content = (content or "").strip()
    if not normalized_content:
        raise ValidationError("Le message ne peut pas être vide.")
    if len(normalized_content) > settings.AI_MESSAGE_MAX_CHARS:
        raise ValidationError("Le message est trop long.")
    message = AssistantMessage(
        conversation=locked,
        role=role,
        status=status or AssistantMessage.Status.COMPLETED,
        content=normalized_content,
        error_code=error_code,
    )
    message.full_clean()
    message.save()
    locked.save(update_fields=("updated_at",))
    return message


def context_messages(*, user, conversation):
    if conversation.user_id != user.pk:
        raise PermissionDenied("Cette conversation ne vous appartient pas.")
    messages = conversation.messages.filter(status=AssistantMessage.Status.COMPLETED).order_by(
        "-created_at", "-pk"
    )[: settings.AI_CONTEXT_MAX_MESSAGES]
    return [
        {"role": message.role, "content": message.content} for message in reversed(list(messages))
    ]


@transaction.atomic
def archive_conversation(*, user, conversation):
    locked = AssistantConversation.objects.select_for_update().get(pk=conversation.pk)
    if locked.user_id != user.pk:
        raise PermissionDenied("Cette conversation ne vous appartient pas.")
    if locked.status == AssistantConversation.Status.ARCHIVED:
        return locked
    locked.status = AssistantConversation.Status.ARCHIVED
    locked.archived_at = timezone.now()
    locked.full_clean()
    locked.save(update_fields=("status", "archived_at", "updated_at"))
    AuditEvent.objects.create(
        organization=locked.organization,
        actor=user,
        action="assistant.conversation_archived",
        target_type="ai_assistant.AssistantConversation",
        target_id=str(locked.pk),
        metadata={},
    )
    return locked
