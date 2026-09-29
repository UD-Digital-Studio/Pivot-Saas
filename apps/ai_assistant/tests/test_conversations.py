from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.ai_assistant.models import AssistantConversation, AssistantMessage
from apps.ai_assistant.selectors import conversation_for_user, conversations_for_user
from apps.ai_assistant.services import (
    add_message,
    archive_conversation,
    context_messages,
    create_conversation,
)
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization


class ConversationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="AI Corp", slug="ai-corp")
        self.other_organization = Organization.objects.create(
            name="Other AI Corp", slug="other-ai-corp"
        )
        self.user = user_model.objects.create_user(
            username="ai-user",
            password="test-password-42",
            organization=self.organization,
            role=user_model.Role.CLIENT,
        )
        self.other_user = user_model.objects.create_user(
            username="other-ai-user",
            password="test-password-42",
            organization=self.other_organization,
            role=user_model.Role.ENGINEER,
        )

    def test_conversation_snapshots_owner_organization(self):
        conversation = create_conversation(user=self.user, title="  Mon chantier  ")

        self.assertEqual(conversation.user, self.user)
        self.assertEqual(conversation.organization, self.organization)
        self.assertEqual(conversation.title, "Mon chantier")
        self.assertGreater(conversation.expires_at, timezone.now())

    def test_selectors_never_return_another_users_conversation(self):
        conversation = create_conversation(user=self.user)

        self.assertFalse(
            conversations_for_user(self.other_user).filter(pk=conversation.pk).exists()
        )
        with self.assertRaisesMessage(Exception, "No AssistantConversation matches"):
            conversation_for_user(self.other_user, conversation.pk)

    def test_another_user_cannot_add_or_read_messages(self):
        conversation = create_conversation(user=self.user)
        add_message(
            user=self.user,
            conversation=conversation,
            role=AssistantMessage.Role.USER,
            content="Quel est mon projet ?",
        )

        with self.assertRaises(PermissionDenied):
            add_message(
                user=self.other_user,
                conversation=conversation,
                role=AssistantMessage.Role.USER,
                content="Donne-moi ses informations",
            )
        with self.assertRaises(PermissionDenied):
            context_messages(user=self.other_user, conversation=conversation)

    @override_settings(AI_CONVERSATION_MAX_MESSAGES=2)
    def test_message_count_is_limited(self):
        conversation = create_conversation(user=self.user)
        for content in ("Question", "Réponse"):
            add_message(
                user=self.user,
                conversation=conversation,
                role=AssistantMessage.Role.USER,
                content=content,
            )

        with self.assertRaisesMessage(ValidationError, "limite de messages"):
            add_message(
                user=self.user,
                conversation=conversation,
                role=AssistantMessage.Role.USER,
                content="Trop tard",
            )

    @override_settings(AI_CONTEXT_MAX_MESSAGES=2)
    def test_context_is_limited_ordered_and_excludes_failed_messages(self):
        conversation = create_conversation(user=self.user)
        add_message(
            user=self.user,
            conversation=conversation,
            role=AssistantMessage.Role.USER,
            content="Ancien",
        )
        add_message(
            user=self.user,
            conversation=conversation,
            role=AssistantMessage.Role.ASSISTANT,
            content="Échec visible dans l’historique seulement",
            status=AssistantMessage.Status.FAILED,
            error_code="provider_timeout",
        )
        add_message(
            user=self.user,
            conversation=conversation,
            role=AssistantMessage.Role.USER,
            content="Récent",
        )
        add_message(
            user=self.user,
            conversation=conversation,
            role=AssistantMessage.Role.ASSISTANT,
            content="Dernière réponse",
        )

        self.assertEqual(
            context_messages(user=self.user, conversation=conversation),
            [
                {"role": "user", "content": "Récent"},
                {"role": "assistant", "content": "Dernière réponse"},
            ],
        )

    def test_expired_or_archived_conversation_rejects_new_messages(self):
        conversation = create_conversation(user=self.user)
        AssistantConversation.objects.filter(pk=conversation.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        conversation.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "expiré"):
            add_message(
                user=self.user,
                conversation=conversation,
                role=AssistantMessage.Role.USER,
                content="Question",
            )

        active = create_conversation(user=self.user)
        archive_conversation(user=self.user, conversation=active)
        with self.assertRaisesMessage(ValidationError, "archivée"):
            add_message(
                user=self.user,
                conversation=active,
                role=AssistantMessage.Role.USER,
                content="Question",
            )

    def test_archive_is_owner_only_and_audited_without_message_content(self):
        conversation = create_conversation(user=self.user, title="Conversation privée")
        with self.assertRaises(PermissionDenied):
            archive_conversation(user=self.other_user, conversation=conversation)

        archived = archive_conversation(user=self.user, conversation=conversation)

        self.assertEqual(archived.status, AssistantConversation.Status.ARCHIVED)
        self.assertIsNotNone(archived.archived_at)
        self.assertFalse(conversations_for_user(self.user).filter(pk=conversation.pk).exists())
        self.assertTrue(
            conversations_for_user(self.user, include_archived=True)
            .filter(pk=conversation.pk)
            .exists()
        )
        event = AuditEvent.objects.get(action="assistant.conversation_archived")
        self.assertEqual(event.actor, self.user)
        self.assertEqual(event.metadata, {})
