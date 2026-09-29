from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class ProjectMembershipTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Members Corp", slug="members-corp")
        self.other_organization = Organization.objects.create(name="Other Corp", slug="other-corp")
        self.engineer = get_user_model().objects.create_user(
            username="members-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="assigned-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.site_manager = get_user_model().objects.create_user(
            username="assigned-manager",
            organization=self.organization,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.foreign_client = get_user_model().objects.create_user(
            username="foreign-client",
            organization=self.other_organization,
            role=get_user_model().Role.CLIENT,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet affectations",
            location="Douala",
            project_date=date.today(),
        )

    def test_owner_can_assign_client_and_site_manager(self):
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:members", kwargs={"pk": self.project.pk}),
            {"members": [self.client_user.pk, self.site_manager.pk]},
        )

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        memberships = self.project.memberships.order_by("project_role")
        self.assertEqual(memberships.count(), 3)
        self.assertEqual(
            set(memberships.values_list("project_role", flat=True)),
            {
                ProjectMembership.Role.OWNER,
                ProjectMembership.Role.SITE_MANAGER,
                ProjectMembership.Role.ENGINEER,
            },
        )

    def test_foreign_user_cannot_be_selected(self):
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:members", kwargs={"pk": self.project.pk}),
            {"members": [self.foreign_client.pk]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sélectionnez un choix valide")
        self.assertFalse(
            self.project.memberships.exclude(project_role=ProjectMembership.Role.ENGINEER).exists()
        )

    def test_assigned_client_can_view_project(self):
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=self.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.name)

    def test_removing_assignment_revokes_project_access(self):
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=self.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.client.force_login(self.engineer)
        self.client.post(reverse("projects:members", kwargs={"pk": self.project.pk}), {})
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))

        self.assertEqual(response.status_code, 404)

    def test_assigned_client_dashboard_counts_only_assigned_project(self):
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=self.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.CLIENT})
        )

        self.assertEqual(response.context["project_stats"]["total"], 1)
        self.assertContains(response, self.project.name)
