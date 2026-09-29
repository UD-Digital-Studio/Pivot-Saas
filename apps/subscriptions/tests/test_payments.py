from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.finance.gateways import FakePaymentGateway
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPayment, SubscriptionPlan
from apps.subscriptions.services import (
    add_calendar_months,
    initiate_subscription_payment,
    process_subscription_deadlines,
)


class SubscriptionPaymentTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Pay Corp", slug="pay-corp")
        self.engineer = User.objects.create_user(
            username="payer", password="password123", organization=self.organization,
            role=User.Role.ENGINEER,
        )
        self.plan = SubscriptionPlan.objects.get(code="professional")
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan,
            status=OrganizationSubscription.Status.TRIAL,
            trial_started_at=now, trial_ends_at=add_calendar_months(now, 3),
        )

    def test_server_calculates_price_and_success_activates_subscription(self):
        payment, created = initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="yearly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"),
        )
        self.assertTrue(created)
        self.assertEqual(payment.amount, self.plan.yearly_price)
        self.assertEqual(payment.status, SubscriptionPayment.Status.SUCCESS)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.ACTIVE)
        self.assertEqual(self.subscription.billing_cycle, "yearly")

    def test_failed_payment_does_not_change_subscription_period(self):
        payment, _ = initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="monthly",
            operator="ORANGE", phone="690000000", gateway=FakePaymentGateway("failed"),
        )
        self.assertEqual(payment.status, SubscriptionPayment.Status.FAILED)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.TRIAL)
        self.assertIsNone(self.subscription.current_period_ends_at)

    def test_zero_price_quote_plan_is_never_sent_to_gateway(self):
        quote_plan = SubscriptionPlan.objects.get(code="enterprise")
        with self.assertRaises(ValidationError):
            initiate_subscription_payment(
                actor=self.engineer, plan=quote_plan, billing_cycle="monthly",
                operator="ORANGE", phone="690000000", gateway=FakePaymentGateway("success"),
            )
        self.assertFalse(SubscriptionPayment.objects.exists())

    def test_refused_and_cancelled_payments_never_activate_subscription(self):
        for status in ("refused", "cancelled"):
            payment, _ = initiate_subscription_payment(
                actor=self.engineer, plan=self.plan, billing_cycle="monthly",
                operator="ORANGE", phone="690000000", gateway=FakePaymentGateway(status),
            )
            self.assertEqual(payment.status, status)
            self.assertIsNone(payment.receipt_reference)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.TRIAL)

    def test_uncertain_payment_blocks_second_attempt(self):
        first, first_created = initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="monthly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("pending"),
        )
        second, second_created = initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="yearly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"),
        )
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SubscriptionPayment.objects.count(), 1)

    def test_renewal_preserves_remaining_paid_days(self):
        now = timezone.now()
        old_end = add_calendar_months(now, 2)
        self.subscription.status = OrganizationSubscription.Status.ACTIVE
        self.subscription.current_period_started_at = now
        self.subscription.current_period_ends_at = old_end
        self.subscription.save()
        initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="monthly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.current_period_ends_at, add_calendar_months(old_end, 1))

    def test_downgrade_is_scheduled_then_applied_at_deadline(self):
        essential = SubscriptionPlan.objects.get(code="essential")
        now = timezone.now()
        old_end = add_calendar_months(now, 1)
        self.subscription.status = OrganizationSubscription.Status.ACTIVE
        self.subscription.current_period_started_at = now
        self.subscription.current_period_ends_at = old_end
        self.subscription.save()
        payment, _ = initiate_subscription_payment(
            actor=self.engineer, plan=essential, billing_cycle="monthly",
            operator="ORANGE", phone="690000000", gateway=FakePaymentGateway("success"),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(payment.action, SubscriptionPayment.Action.DOWNGRADE)
        self.assertEqual(self.subscription.plan, self.plan)
        self.assertEqual(self.subscription.pending_plan, essential)
        self.assertEqual(process_subscription_deadlines(now=old_end), 1)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.plan, essential)
        self.assertIsNone(self.subscription.pending_plan)
        self.assertEqual(process_subscription_deadlines(now=old_end), 0)

    def test_upgrade_is_immediate_and_keeps_paid_end_date_as_extension_base(self):
        essential = SubscriptionPlan.objects.get(code="essential")
        now = timezone.now()
        old_end = add_calendar_months(now, 1)
        self.subscription.plan = essential
        self.subscription.plan_snapshot = essential.snapshot()
        self.subscription.status = OrganizationSubscription.Status.ACTIVE
        self.subscription.current_period_started_at = now
        self.subscription.current_period_ends_at = old_end
        self.subscription.save()
        payment, _ = initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="monthly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(payment.action, SubscriptionPayment.Action.UPGRADE)
        self.assertEqual(self.subscription.plan, self.plan)
        self.assertEqual(self.subscription.current_period_ends_at, add_calendar_months(old_end, 1))

    def test_successful_renewal_restores_read_only_access_state(self):
        self.subscription.status = OrganizationSubscription.Status.READ_ONLY
        self.subscription.current_period_started_at = timezone.now() - timezone.timedelta(days=40)
        self.subscription.current_period_ends_at = timezone.now() - timezone.timedelta(days=10)
        self.subscription.save()
        initiate_subscription_payment(
            actor=self.engineer, plan=self.plan, billing_cycle="monthly",
            operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.ACTIVE)
