from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription, SubscriptionNoticeDelivery, SubscriptionPlan
from apps.subscriptions.services import process_subscription_notices


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SubscriptionNoticeTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Notice Corp", slug="notice-corp")
        self.engineer = User.objects.create_user(
            username="notice-engineer", email="engineer@example.com", organization=self.organization,
            role=User.Role.ENGINEER,
        )
        self.admin = User.objects.create_user(
            username="notice-admin", email="admin@example.com", organization=self.organization,
            role=User.Role.ADMIN,
        )
        self.client_user = User.objects.create_user(
            username="notice-client", email="client@example.com", organization=self.organization,
            role=User.Role.CLIENT,
        )
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=SubscriptionPlan.objects.get(code="professional"),
            status=OrganizationSubscription.Status.TRIAL, trial_started_at=now,
            trial_ends_at=now + timezone.timedelta(days=7),
        )

    def test_j7_notice_targets_engineers_and_admins_and_is_idempotent(self):
        first = process_subscription_notices(now=timezone.now())
        second = process_subscription_notices(now=timezone.now())
        self.assertEqual(first, 4)
        self.assertEqual(second, 0)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(SubscriptionNoticeDelivery.objects.count(), 4)
        self.assertFalse(Notification.objects.filter(recipient=self.client_user).exists())
        self.assertIn("English", mail.outbox[0].body)
        self.assertIn("PIVOT", mail.outbox[0].subject)
