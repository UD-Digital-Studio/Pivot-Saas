from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.organizations.models import Organization
from apps.subscriptions.models import (
    OrganizationSubscription,
    SubscriptionEvent,
    SubscriptionPlan,
)
from apps.subscriptions.services import add_calendar_months, start_organization_trial


@override_settings(SUBSCRIPTION_TRIAL_MONTHS=3, SUBSCRIPTION_TRIAL_PLAN_CODE="professional")
class TrialServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Trial Corp", slug="trial-corp")
        self.plan = SubscriptionPlan.objects.get(code="professional")

    def test_add_three_calendar_months_clamps_end_of_month(self):
        value = timezone.make_aware(datetime(2027, 1, 31, 10, 30))
        result = add_calendar_months(value, 3)
        self.assertEqual(result, timezone.make_aware(datetime(2027, 4, 30, 10, 30)))

    def test_trial_starts_for_exactly_three_calendar_months(self):
        activated_at = timezone.make_aware(datetime(2026, 8, 28, 9, 15))

        subscription, created = start_organization_trial(
            organization=self.organization,
            activated_at=activated_at,
        )

        self.assertTrue(created)
        self.assertEqual(subscription.status, OrganizationSubscription.Status.TRIAL)
        self.assertEqual(
            subscription.trial_ends_at,
            timezone.make_aware(datetime(2026, 11, 28, 9, 15)),
        )
        self.assertEqual(subscription.plan, self.plan)
        event = SubscriptionEvent.objects.get(subscription=subscription)
        self.assertEqual(event.event_type, "subscription.trial_started")
        self.assertEqual(event.metadata["trial_months"], 3)

    def test_trial_is_created_only_once_for_an_organization(self):
        first, first_created = start_organization_trial(organization=self.organization)
        second, second_created = start_organization_trial(organization=self.organization)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(OrganizationSubscription.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.count(), 1)


class PricingViewTests(TestCase):
    def test_public_pricing_lists_plans_quotas_and_client_rule(self):
        response = self.client.get(reverse("subscriptions:pricing"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "subscriptions/pricing.html")
        self.assertContains(response, "Retour à la connexion")
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, "Essentiel")
        self.assertContains(response, "Professionnel")
        self.assertContains(response, "Entreprise")
        self.assertContains(response, "3 projets actifs")
        self.assertContains(response, "30 membres internes actifs")
        self.assertContains(response, "Clients illimités et non comptabilisés", count=3)
        self.assertContains(response, "essai unique de trois mois")

    def test_pricing_switches_between_monthly_and_yearly_prices(self):
        monthly = self.client.get(reverse("subscriptions:pricing"), {"cycle": "monthly"})
        yearly = self.client.get(reverse("subscriptions:pricing"), {"cycle": "yearly"})

        self.assertContains(monthly, "25000")
        self.assertContains(monthly, "par mois")
        self.assertContains(yearly, "250000")
        self.assertContains(yearly, "par an")

    def test_authenticated_engineer_sees_exact_trial_end_date(self):
        organization = Organization.objects.create(name="Visible Trial", slug="visible-trial")
        engineer = get_user_model().objects.create_user(
            username="trial-engineer",
            password="ing12345",
            organization=organization,
            role=get_user_model().Role.ENGINEER,
        )
        started_at = timezone.make_aware(datetime(2026, 9, 5, 12, 0))
        subscription = OrganizationSubscription.objects.create(
            organization=organization,
            plan=SubscriptionPlan.objects.get(code="professional"),
            status=OrganizationSubscription.Status.TRIAL,
            trial_started_at=started_at,
            trial_ends_at=add_calendar_months(started_at, 3),
        )
        self.client.force_login(engineer)

        response = self.client.get(reverse("subscriptions:pricing"))

        self.assertContains(response, "Votre essai est actif jusqu’au")
        self.assertContains(response, subscription.trial_ends_at.strftime("%Y"))
