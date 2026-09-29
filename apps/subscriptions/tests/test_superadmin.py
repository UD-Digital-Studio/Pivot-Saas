from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription, SubscriptionEvent, SubscriptionPlan


class SubscriptionSuperAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="billing-root", password="password123")
        self.organization = Organization.objects.create(name="Billing Org", slug="billing-org")
        self.plan = SubscriptionPlan.objects.get(code="professional")
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan,
            status=OrganizationSubscription.Status.ACTIVE,
            current_period_started_at=now, current_period_ends_at=now + timezone.timedelta(days=30),
        )
        self.client.force_login(self.admin)

    def test_subscription_console_lists_usage_and_filters(self):
        response = self.client.get(reverse("superadmin:subscription-list"), {"q": "Billing", "status": "active"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Billing Org")
        self.assertContains(response, "Professionnel")
        self.assertContains(response, "Prévisualiser les tarifs")

    def test_plan_creation_is_confirmed_and_audited(self):
        response = self.client.post(reverse("superadmin:subscription-plan-create"), {
            "confirmed": "yes", "name": "Test Plus", "code": "test-plus",
            "description": "Test", "monthly_price": "5000", "yearly_price": "50000",
            "currency": "XAF", "max_active_projects": "2", "max_internal_members": "4",
            "storage_limit_mb": "100", "display_order": "9", "is_active": "on", "is_public": "on",
        })
        self.assertRedirects(response, reverse("superadmin:subscription-list"))
        plan = SubscriptionPlan.objects.get(code="test-plus")
        self.assertTrue(AuditEvent.objects.filter(action="subscription_plan.created", target_id=str(plan.pk)).exists())

    def test_intervention_suspends_without_creating_payment_and_is_audited(self):
        token = self.subscription.updated_at.isoformat()
        response = self.client.post(reverse("superadmin:subscription-intervene", kwargs={"pk": self.subscription.pk}), {
            "confirmed": "yes", "expected_updated_at": token, "action": "suspend",
            "reason": "Incident commercial vérifié",
        })
        self.assertRedirects(response, reverse("superadmin:subscription-list"))
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.SUSPENDED)
        self.assertTrue(SubscriptionEvent.objects.filter(subscription=self.subscription, event_type="subscription.admin_suspend").exists())
        event = AuditEvent.objects.get(action="subscription.admin_suspend")
        self.assertEqual(event.metadata["reason"], "Incident commercial vérifié")
        self.assertFalse(self.subscription.payments.exists())

    def test_stale_confirmation_cannot_apply_twice(self):
        token = self.subscription.updated_at.isoformat()
        payload = {"confirmed": "yes", "expected_updated_at": token, "action": "extend", "extension_days": "10", "reason": "Geste commercial"}
        self.client.post(reverse("superadmin:subscription-intervene", kwargs={"pk": self.subscription.pk}), payload)
        self.subscription.refresh_from_db()
        first_end = self.subscription.current_period_ends_at
        self.client.post(reverse("superadmin:subscription-intervene", kwargs={"pk": self.subscription.pk}), payload)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.current_period_ends_at, first_end)
        self.assertEqual(SubscriptionEvent.objects.filter(subscription=self.subscription, event_type="subscription.admin_extend").count(), 1)
