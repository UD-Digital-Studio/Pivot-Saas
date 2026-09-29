from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.subscriptions.models import OrganizationSubscription, SubscriptionPlan
from apps.subscriptions.services import process_subscription_deadlines


class SubscriptionRestrictionMatrixTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Matrix", slug="matrix")
        self.other_organization = Organization.objects.create(name="Matrix Other", slug="matrix-other")
        self.plan = SubscriptionPlan.objects.get(code="professional")
        now = timezone.now()
        self.subscription = OrganizationSubscription.objects.create(
            organization=self.organization, plan=self.plan,
            status=OrganizationSubscription.Status.READ_ONLY,
            current_period_started_at=now - timezone.timedelta(days=40),
            current_period_ends_at=now - timezone.timedelta(days=10),
        )
        self.users = {
            role: User.objects.create_user(
                username=f"matrix-{role}", password="password123",
                organization=self.organization, role=role,
            )
            for role in (User.Role.CLIENT, User.Role.SITE_MANAGER, User.Role.ENGINEER, User.Role.ADMIN)
        }
        self.superuser = User.objects.create_superuser(username="matrix-root", password="password123")

    def test_html_and_ajax_write_matrix_for_all_organization_roles(self):
        for role, user in self.users.items():
            with self.subTest(role=role, channel="html"):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse("projects:list")).status_code, 200)
                response = self.client.post(reverse("projects:create"), {})
                self.assertRedirects(response, reverse("subscriptions:pricing"))
            with self.subTest(role=role, channel="ajax"):
                response = self.client.post(reverse("projects:create"), {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"], "subscription_read_only")

    def test_superuser_is_not_blocked_by_tenant_subscription_middleware(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse("projects:create"), {}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertNotEqual(getattr(response, "json", lambda: {})().get("error") if response.headers.get("Content-Type", "").startswith("application/json") else None, "subscription_read_only")

    def test_expiration_never_deletes_tenant_data_or_other_tenant_data(self):
        engineer = self.users[User.Role.ENGINEER]
        project = Project.objects.create(organization=self.organization, engineer=engineer, name="Conservé", location="Yaoundé", project_date=date.today())
        other_engineer = User.objects.create_user(username="other-eng", organization=self.other_organization, role=User.Role.ENGINEER)
        other_project = Project.objects.create(organization=self.other_organization, engineer=other_engineer, name="Isolé", location="Douala", project_date=date.today())
        self.subscription.status = OrganizationSubscription.Status.GRACE
        self.subscription.grace_ends_at = timezone.now() - timezone.timedelta(seconds=1)
        self.subscription.save()
        process_subscription_deadlines()
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, OrganizationSubscription.Status.READ_ONLY)
        self.assertTrue(Project.objects.filter(pk=project.pk, organization=self.organization).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk, organization=self.other_organization).exists())
