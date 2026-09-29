from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.control_room import pilot_economy_metrics
from apps.audit.models import (
    AuditEvent, PilotPricingHypothesis, PilotRecommendation,
)
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership, ProjectOnboarding
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan


class PilotEconomyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Pilote E22", slug="pilote-e22")
        cls.admin = get_user_model().objects.create_superuser(
            username="pilot-admin", password="admin12345", role=get_user_model().Role.ADMIN
        )
        cls.engineer = get_user_model().objects.create_user(
            username="pilot-engineer", organization=cls.organization,
            role=get_user_model().Role.ENGINEER,
        )
        cls.client_user = get_user_model().objects.create_user(
            username="pilot-client", organization=cls.organization,
            role=get_user_model().Role.CLIENT,
        )
        cls.contractor = get_user_model().objects.create_user(
            username="pilot-contractor", organization=cls.organization,
            role=get_user_model().Role.CONTRACTOR,
        )
        cls.project = Project.objects.create(
            organization=cls.organization, engineer=cls.engineer, name="Chantier pilote",
            location="Douala", project_date=date.today(), status=Project.Status.ONGOING,
        )
        ProjectOnboarding.objects.create(
            organization=cls.organization, project=cls.project,
            route=ProjectOnboarding.Route.CLIENT_LED,
            status=ProjectOnboarding.Status.ACTIVE,
            financial_conditions="Conditions pilote", initiated_by=cls.engineer,
            activated_by=cls.client_user, activated_at=timezone.now(),
        )
        ProjectMembership.objects.create(
            organization=cls.organization, project=cls.project, user=cls.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        ProjectMembership.objects.create(
            organization=cls.organization, project=cls.project, user=cls.contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        get_user_model().objects.filter(pk=cls.client_user.pk).update(last_login=timezone.now())
        cls.plan = SubscriptionPlan.objects.create(
            name="Pilote Pro", code="pilote-pro", monthly_price=24000,
            yearly_price=240000, currency="XAF",
        )
        now = timezone.now()
        OrganizationSubscription.objects.create(
            organization=cls.organization, plan=cls.plan,
            status=OrganizationSubscription.Status.ACTIVE,
            billing_cycle=OrganizationSubscription.BillingCycle.YEARLY,
            current_period_started_at=now,
            current_period_ends_at=now + timedelta(days=365),
            plan_snapshot=cls.plan.snapshot(),
        )

    def test_metrics_measure_retention_nps_mrr_and_pricing(self):
        PilotRecommendation.objects.create(
            organization=self.organization, respondent_role="client", score=10,
            recorded_by=self.admin,
        )
        PilotRecommendation.objects.create(
            organization=self.organization, respondent_role="contractor", score=5,
            recorded_by=self.admin,
        )
        hypothesis = PilotPricingHypothesis.objects.create(
            segment="PME BTP", plan=self.plan, proposed_monthly_price=30000,
            sample_size=10, positive_responses=7,
            status=PilotPricingHypothesis.Status.VALIDATED,
            assumptions="Les équipes valorisent la validation et le suivi des preuves.",
            recorded_by=self.admin,
        )

        metrics = pilot_economy_metrics(
            date_from=timezone.localdate() - timedelta(days=1),
            date_to=timezone.localdate() + timedelta(days=1),
        )

        self.assertEqual(metrics["retention"]["client"]["rate"], 100.0)
        self.assertEqual(metrics["retention"]["contractor"]["rate"], 0.0)
        self.assertEqual(metrics["nps"], 0.0)
        self.assertEqual(metrics["mrr"], 20000)
        self.assertEqual(metrics["validated_hypothesis_count"], 1)
        self.assertEqual(hypothesis.positive_rate, 70.0)

    def test_superadmin_can_record_recommendation_with_audit_event(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("superadmin:pilot-recommendation-create"),
            {
                "organization": self.organization.pk,
                "respondent_role": PilotRecommendation.RespondentRole.CLIENT,
                "score": 9,
                "note": "Je recommanderais PIVOT.",
                "confirmed": "yes",
            },
        )

        self.assertRedirects(response, reverse("superadmin:project-list"))
        recommendation = PilotRecommendation.objects.get(score=9)
        self.assertEqual(recommendation.recorded_by, self.admin)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="pilot.recommendation_recorded", target_id=str(recommendation.pk)
            ).exists()
        )

    def test_regular_user_cannot_record_pilot_measure(self):
        self.client.force_login(self.engineer)
        response = self.client.post(
            reverse("superadmin:pilot-pricing-create"),
            {
                "segment": "PME", "plan": self.plan.pk,
                "proposed_monthly_price": 30000, "sample_size": 1,
                "positive_responses": 1, "status": "testing",
                "assumptions": "Test", "confirmed": "yes",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PilotPricingHypothesis.objects.exists())
