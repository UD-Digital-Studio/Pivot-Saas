from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.alpha = Organization.objects.create(name="Dashboard Alpha", slug="dashboard-alpha")
        self.beta = Organization.objects.create(name="Dashboard Beta", slug="dashboard-beta")
        self.engineer = get_user_model().objects.create_user(
            username="dashboard-engineer",
            organization=self.alpha,
            role=get_user_model().Role.ENGINEER,
        )
        self.other_engineer = get_user_model().objects.create_user(
            username="dashboard-other-engineer",
            organization=self.beta,
            role=get_user_model().Role.ENGINEER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="dashboard-client",
            organization=self.alpha,
            role=get_user_model().Role.CLIENT,
        )
        self.site_manager = get_user_model().objects.create_user(
            username="dashboard-manager",
            organization=self.alpha,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.alpha_project = Project.objects.create(
            organization=self.alpha,
            engineer=self.engineer,
            name="Chantier Alpha",
            location="Douala",
            project_date=date.today(),
            status=Project.Status.ONGOING,
            budget_amount=5000000,
        )
        Project.objects.create(
            organization=self.beta,
            engineer=self.other_engineer,
            name="Chantier Beta secret",
            location="Yaoundé",
            project_date=date.today(),
            status=Project.Status.ONGOING,
            budget_amount=9000000,
        )

    def assign(self, user):
        return ProjectMembership.objects.create(
            organization=self.alpha,
            project=self.alpha_project,
            user=user,
            project_role=(
                ProjectMembership.Role.OWNER
                if user.role == user.Role.CLIENT
                else ProjectMembership.Role.SITE_MANAGER
            ),
        )

    def test_engineer_dashboard_excludes_other_organization(self):
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER})
        )

        self.assertEqual(response.context["project_stats"]["total"], 1)
        self.assertContains(response, "Chantier Alpha")
        self.assertNotContains(response, "Chantier Beta secret")

    def test_client_dashboard_contains_only_assigned_projects(self):
        self.assign(self.client_user)
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.CLIENT})
        )

        self.assertContains(response, "Client")
        self.assertContains(response, "Chantier Alpha")
        self.assertContains(response, "Nouveau projet")

    def test_site_manager_dashboard_contains_assigned_projects(self):
        self.assign(self.site_manager)
        self.client.force_login(self.site_manager)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.SITE_MANAGER})
        )

        self.assertEqual(response.context["project_stats"]["total"], 1)
        self.assertContains(response, "Responsable de chantier")

    def test_unassigned_client_gets_explicit_empty_state(self):
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.CLIENT})
        )

        self.assertEqual(response.context["project_stats"]["total"], 0)
        self.assertContains(response, "Aucun projet")

    def test_dashboard_search_and_status_filter_are_functional(self):
        Project.objects.create(
            organization=self.alpha,
            engineer=self.engineer,
            name="Villa Bonapriso",
            location="Bonapriso",
            project_date=date.today(),
            status=Project.Status.COMPLETE,
        )
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER}),
            {"q": "Bonapriso", "status": Project.Status.COMPLETE},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Villa Bonapriso")
        self.assertNotContains(response, "Chantier Alpha")
        self.assertEqual(response.context["dashboard_query"], "Bonapriso")
        self.assertEqual(response.context["selected_status"], Project.Status.COMPLETE)

    def test_dashboard_filter_never_exposes_another_organization(self):
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER}),
            {"q": "secret"},
        )

        self.assertEqual(response.context["recent_projects"].paginator.count, 0)
        self.assertNotContains(response, "Chantier Beta secret")

    def test_site_manager_gets_role_specific_active_stage_metric(self):
        self.assign(self.site_manager)
        self.client.force_login(self.site_manager)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.SITE_MANAGER})
        )

        self.assertEqual(response.context["role_metric"]["kind"], "active_stages")
        self.assertContains(response, "Étapes actives")

    def test_project_list_is_paginated(self):
        for index in range(13):
            Project.objects.create(
                organization=self.alpha,
                engineer=self.engineer,
                name=f"Projet pagination {index:02d}",
                location="Douala",
                project_date=date.today(),
            )
        self.client.force_login(self.engineer)

        first_page = self.client.get(reverse("projects:list"))
        second_page = self.client.get(reverse("projects:list"), {"page": 2})

        self.assertEqual(len(first_page.context["page"].object_list), 12)
        self.assertEqual(second_page.context["page"].number, 2)
        self.assertEqual(first_page.context["page"].paginator.count, 14)
