from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.organizations.models import Organization
from apps.subscriptions.models import (
    OrganizationSubscription,
    SubscriptionEvent,
    SubscriptionPlan,
)


class SubscriptionModelsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Genius", slug="genius-subscription")
        cls.plan, _ = SubscriptionPlan.objects.update_or_create(
            code="professional",
            defaults={
                "name": "Professionnel",
                "monthly_price": Decimal("25000"),
                "yearly_price": Decimal("250000"),
                "max_active_projects": 15,
                "max_internal_members": 30,
                "storage_limit_mb": 20_480,
                "advanced_reports_enabled": True,
                "ai_assistant_enabled": True,
            },
        )

    def trial_subscription(self, **overrides):
        started_at = timezone.now()
        values = {
            "organization": self.organization,
            "plan": self.plan,
            "status": OrganizationSubscription.Status.TRIAL,
            "trial_started_at": started_at,
            "trial_ends_at": started_at + timedelta(days=92),
        }
        values.update(overrides)
        return OrganizationSubscription.objects.create(**values)

    def test_plan_supports_limited_and_unlimited_quotas(self):
        self.assertEqual(self.plan.max_active_projects, 15)
        self.assertEqual(self.plan.max_internal_members, 30)
        unlimited = SubscriptionPlan.objects.create(
            name="Entreprise",
            code="enterprise-test",
            monthly_price=0,
            yearly_price=0,
            max_active_projects=None,
            max_internal_members=None,
            storage_limit_mb=None,
        )
        unlimited.full_clean()

    def test_plan_rejects_zero_quota_and_negative_price(self):
        invalid = SubscriptionPlan(
            name="Invalide",
            code="invalid",
            monthly_price=-1,
            yearly_price=0,
            max_internal_members=0,
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()

    def test_plan_snapshot_preserves_commercial_values(self):
        subscription = self.trial_subscription()
        initial_snapshot = subscription.plan_snapshot.copy()

        self.plan.monthly_price = 30_000
        self.plan.max_internal_members = 40
        self.plan.save(update_fields=("monthly_price", "max_internal_members"))
        subscription.refresh_from_db()

        self.assertEqual(initial_snapshot["monthly_price"], "25000")
        self.assertEqual(subscription.plan_snapshot["monthly_price"], "25000")
        self.assertEqual(subscription.plan_snapshot["max_internal_members"], 30)

    def test_only_one_current_subscription_exists_per_organization(self):
        self.trial_subscription()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationSubscription.objects.create(
                organization=self.organization,
                plan=self.plan,
                status=OrganizationSubscription.Status.SUSPENDED,
            )

    def test_trial_requires_complete_dates(self):
        subscription = OrganizationSubscription(
            organization=self.organization,
            plan=self.plan,
            status=OrganizationSubscription.Status.TRIAL,
        )
        with self.assertRaises(ValidationError) as error:
            subscription.full_clean()
        self.assertIn("trial_ends_at", error.exception.message_dict)

    def test_active_grace_and_cancelled_statuses_require_their_dates(self):
        for status, field in (
            (OrganizationSubscription.Status.ACTIVE, "current_period_ends_at"),
            (OrganizationSubscription.Status.GRACE, "current_period_ends_at"),
            (OrganizationSubscription.Status.READ_ONLY, "current_period_ends_at"),
            (OrganizationSubscription.Status.CANCELLED, "cancelled_at"),
        ):
            subscription = OrganizationSubscription(
                organization=self.organization,
                plan=self.plan,
                status=status,
            )
            with self.subTest(status=status), self.assertRaises(ValidationError) as error:
                subscription.full_clean()
            self.assertIn(field, error.exception.message_dict)

    def test_database_rejects_reversed_trial_dates(self):
        now = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrganizationSubscription.objects.create(
                organization=self.organization,
                plan=self.plan,
                status=OrganizationSubscription.Status.TRIAL,
                trial_started_at=now,
                trial_ends_at=now - timedelta(seconds=1),
            )

    def test_event_keeps_status_and_plan_snapshot(self):
        subscription = self.trial_subscription()
        actor = get_user_model().objects.create_superuser(
            username="subscription-admin",
            password="admin12345",
        )

        event = SubscriptionEvent.objects.create(
            subscription=subscription,
            actor=actor,
            event_type="subscription.created",
            previous_status="",
            new_status=OrganizationSubscription.Status.TRIAL,
            metadata={"source": "test"},
        )

        self.assertEqual(event.plan_snapshot["code"], "professional")
        self.assertEqual(event.new_status, OrganizationSubscription.Status.TRIAL)
        self.assertEqual(event.metadata, {"source": "test"})

    def test_plan_and_organization_are_protected_while_subscription_exists(self):
        self.trial_subscription()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriptionPlan.objects.filter(pk=self.plan.pk).delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.filter(pk=self.organization.pk).delete()
