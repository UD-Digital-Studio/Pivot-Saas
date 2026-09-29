from datetime import date

from django.test import TestCase
from django.urls import reverse
from uuid import uuid4
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan


class SubscriptionAccessMiddlewareTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Restricted", slug="restricted")
        self.user = User.objects.create_user(
            username="restricted-engineer", password="password123",
            organization=self.organization, role=User.Role.ENGINEER,
        )
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=SubscriptionPlan.objects.get(code="professional"),
            status=OrganizationSubscription.Status.ACTIVE,
            current_period_started_at=now - timezone.timedelta(days=30),
            current_period_ends_at=now + timezone.timedelta(days=1),
        )
        self.client.force_login(self.user)

    def test_read_only_keeps_get_access_and_blocks_html_writes(self):
        self.subscription.status = OrganizationSubscription.Status.READ_ONLY
        self.subscription.save(update_fields=("status",))
        listing = self.client.get(reverse("projects:list"))
        blocked = self.client.post(reverse("projects:create"), {})
        self.assertEqual(listing.status_code, 200)
        self.assertRedirects(blocked, reverse("subscriptions:pricing"))

    def test_ajax_write_receives_structured_403(self):
        self.subscription.status = OrganizationSubscription.Status.READ_ONLY
        self.subscription.save(update_fields=("status",))
        response = self.client.post(
            reverse("projects:create"), {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "subscription_read_only")
        self.assertEqual(response.json()["billing_url"], "/tarifs/")

    def test_grace_period_remains_writable(self):
        self.subscription.status = OrganizationSubscription.Status.GRACE
        self.subscription.grace_ends_at = timezone.now() + timezone.timedelta(days=7)
        self.subscription.save(update_fields=("status", "grace_ends_at"))
        response = self.client.post(reverse("projects:create"), {})
        self.assertEqual(response.status_code, 200)

    def test_billing_is_available_while_read_only(self):
        self.subscription.status = OrganizationSubscription.Status.READ_ONLY
        self.subscription.save(update_fields=("status",))
        response = self.client.post(reverse("subscriptions:pay"), {})
        self.assertRedirects(response, reverse("subscriptions:pricing"))

    def test_read_only_blocks_get_based_report_generation(self):
        self.subscription.status = OrganizationSubscription.Status.READ_ONLY
        self.subscription.save(update_fields=("status",))
        response = self.client.get(reverse("reporting:pdf", kwargs={"pk": uuid4()}))
        self.assertRedirects(response, reverse("subscriptions:pricing"))

    def test_plan_features_are_read_from_contract_snapshot(self):
        essential = SubscriptionPlan.objects.get(code="essential")
        self.subscription.plan = essential
        self.subscription.plan_snapshot = essential.snapshot()
        self.subscription.save(update_fields=("plan", "plan_snapshot"))
        response = self.client.get(reverse("ai_assistant:conversation-panel"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertIn("forfait", response.json()["disabled_reason"])

    def external_project(self, *, project_status, home_status):
        self.subscription.status = home_status
        self.subscription.save(update_fields=("status",))
        project_organization = Organization.objects.create(
            name=f"Projet externe {project_status}",
            slug=f"projet-externe-{project_status}",
        )
        OrganizationSubscription.objects.create(
            organization=project_organization,
            plan=SubscriptionPlan.objects.get(code="professional"),
            status=project_status,
            current_period_started_at=timezone.now() - timezone.timedelta(days=1),
            current_period_ends_at=timezone.now() + timezone.timedelta(days=30),
        )
        project = Project.objects.create(
            organization=project_organization,
            name="Chantier externe",
            location="Yaoundé",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=project_organization,
            project=project,
            user=self.user,
            project_role=ProjectMembership.Role.SITE_MANAGER,
        )
        return project

    def test_external_project_uses_project_read_only_subscription(self):
        project = self.external_project(
            project_status=OrganizationSubscription.Status.READ_ONLY,
            home_status=OrganizationSubscription.Status.ACTIVE,
        )

        response = self.client.post(
            reverse("collaboration:comment-create", kwargs={"project_pk": project.pk}),
            {"content": "Commentaire externe"},
        )

        self.assertRedirects(response, reverse("subscriptions:pricing"))

    def test_external_project_ignores_home_read_only_subscription(self):
        project = self.external_project(
            project_status=OrganizationSubscription.Status.ACTIVE,
            home_status=OrganizationSubscription.Status.READ_ONLY,
        )

        response = self.client.post(
            reverse("collaboration:comment-create", kwargs={"project_pk": project.pk}),
            {"content": "Commentaire autorisé"},
        )

        self.assertNotEqual(response.url, reverse("subscriptions:pricing"))
        self.assertTrue(project.comments.filter(author=self.user).exists())

    def test_project_page_exposes_project_subscription_to_templates(self):
        project = self.external_project(
            project_status=OrganizationSubscription.Status.GRACE,
            home_status=OrganizationSubscription.Status.ACTIVE,
        )

        response = self.client.get(project.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["access_subscription"].organization,
            project.organization,
        )
        self.assertTrue(response.context["subscription_is_grace"])
