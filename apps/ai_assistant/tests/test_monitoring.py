from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.ai_assistant.models import AssistantMessage, AssistantRequest
from apps.ai_assistant.monitoring import assistant_health_snapshot
from apps.ai_assistant.services import create_conversation
from apps.organizations.models import Organization


@override_settings(
    OPENROUTER_ENABLED=True,
    OPENROUTER_API_KEY="monitoring-key",
    OPENROUTER_MODEL="test/model",
)
class AssistantMonitoringTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.organization = Organization.objects.create(name="Monitor", slug="monitor")
        self.user = user_model.objects.create_user(
            username="monitored-user",
            organization=self.organization,
            role=user_model.Role.ENGINEER,
        )
        self.superuser = user_model.objects.create_superuser(
            username="platform-monitor", password="test-password-42"
        )
        self.conversation = create_conversation(user=self.user)

    def create_request(self, **values):
        defaults = {
            "organization": self.organization,
            "user": self.user,
            "conversation": self.conversation,
            "request_hash": f"{AssistantRequest.objects.count():064d}",
        }
        defaults.update(values)
        return AssistantRequest.objects.create(**defaults)

    def test_snapshot_contains_aggregates_without_conversation_content(self):
        self.create_request(
            status=AssistantRequest.Status.SUCCESS,
            latency_ms=120,
            total_tokens=30,
        )
        self.create_request(
            status=AssistantRequest.Status.FAILED,
            latency_ms=300,
            error_code="OpenRouterTimeoutError",
        )
        self.create_request(
            status=AssistantRequest.Status.BLOCKED,
            error_code="prompt_injection",
        )

        snapshot = assistant_health_snapshot()

        self.assertEqual(snapshot["availability"], "operational")
        self.assertEqual(snapshot["volume"], 3)
        self.assertEqual(snapshot["errors"], 1)
        self.assertEqual(snapshot["blocked"], 1)
        self.assertEqual(snapshot["average_latency_ms"], 120)
        self.assertEqual(snapshot["total_tokens"], 30)
        self.assertNotIn("conversation", snapshot)
        self.assertNotIn("content", snapshot)

    def test_superadmin_dashboard_shows_metrics_but_not_messages(self):
        secret = "Contenu privé qui ne doit jamais apparaître dans la supervision"
        AssistantMessage.objects.create(
            conversation=self.conversation,
            role=AssistantMessage.Role.USER,
            content=secret,
        )
        self.create_request(status=AssistantRequest.Status.SUCCESS, total_tokens=5)
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("superadmin:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Supervision de l’assistant IA")
        self.assertNotContains(response, secret)

    @override_settings(OPENROUTER_ENABLED=False)
    def test_disabled_snapshot_is_explicit(self):
        self.assertEqual(assistant_health_snapshot()["availability"], "disabled")
