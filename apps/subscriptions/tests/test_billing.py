from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.finance.gateways import FakePaymentGateway
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan
from apps.subscriptions.services import initiate_subscription_payment


class BillingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Invoice Org", slug="invoice-org")
        self.other_org = Organization.objects.create(name="Other Org", slug="other-org")
        self.user = User.objects.create_user(username="invoice-user", password="password123", organization=self.org, role=User.Role.ENGINEER)
        self.other = User.objects.create_user(username="other-user", password="password123", organization=self.other_org, role=User.Role.ENGINEER)
        self.plan = SubscriptionPlan.objects.get(code="professional")
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(organization=self.org, plan=self.plan, status="trial", trial_started_at=now, trial_ends_at=now + timezone.timedelta(days=90))
        OrganizationSubscription.objects.create(organization=self.other_org, plan=self.plan, status="trial", trial_started_at=now, trial_ends_at=now + timezone.timedelta(days=90))
        self.client.force_login(self.user)

    def test_billing_page_shows_current_plan_usage_payments_and_history(self):
        payment, _ = initiate_subscription_payment(actor=self.user, plan=self.plan, billing_cycle="monthly", operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"))
        response = self.client.get(reverse("subscriptions:billing"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Facturation et historique")
        self.assertContains(response, "subscription.payment_confirmed")

    def test_confirmed_payment_has_unique_pdf_receipt(self):
        payment, _ = initiate_subscription_payment(actor=self.user, plan=self.plan, billing_cycle="monthly", operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"))
        response = self.client.get(reverse("subscriptions:receipt", kwargs={"pk": payment.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(payment.receipt_reference, response["Content-Disposition"])

    def test_unconfirmed_and_cross_organization_receipts_are_forbidden(self):
        failed, _ = initiate_subscription_payment(actor=self.user, plan=self.plan, billing_cycle="monthly", operator="MTN", phone="670000000", gateway=FakePaymentGateway("failed"))
        self.assertEqual(self.client.get(reverse("subscriptions:receipt", kwargs={"pk": failed.pk})).status_code, 403)
        success, _ = initiate_subscription_payment(actor=self.user, plan=self.plan, billing_cycle="monthly", operator="MTN", phone="670000000", gateway=FakePaymentGateway("success"))
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("subscriptions:receipt", kwargs={"pk": success.pk})).status_code, 403)
