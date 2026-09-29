from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.projects.models import Project


class ProjectTests(TestCase):
    def setUp(self):
        self.alpha = Organization.objects.create(name="Alpha Projects", slug="alpha-projects")
        self.beta = Organization.objects.create(name="Beta Projects", slug="beta-projects")
        self.engineer = get_user_model().objects.create_user(
            username="project-engineer",
            password="project-test-password",
            organization=self.alpha,
            role=get_user_model().Role.ENGINEER,
        )
        self.other_engineer = get_user_model().objects.create_user(
            username="other-project-engineer",
            organization=self.beta,
            role=get_user_model().Role.ENGINEER,
        )
        self.project = Project.objects.create(
            organization=self.alpha,
            engineer=self.engineer,
            name="Résidence Alpha",
            description="Construction d'un immeuble résidentiel.",
            location="Douala",
            project_date=date(2026, 8, 20),
            status=Project.Status.ONGOING,
            budget_amount=Decimal("25000000"),
        )

    def test_project_rejects_engineer_from_another_organization(self):
        project = Project(
            organization=self.alpha,
            engineer=self.other_engineer,
            name="Projet invalide",
            location="Yaoundé",
            project_date=date.today(),
        )

        with self.assertRaises(ValidationError):
            project.full_clean()

    def test_engineer_can_create_project_from_interface(self):
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:create"),
            {
                "name": "Centre commercial",
                "description": "Nouveau chantier",
                "location": "Bonamoussadi",
                "project_date": "2026-09-01",
                "status": Project.Status.PENDING,
                "budget_amount": "18000000",
            },
        )

        created = Project.objects.get(name="Centre commercial")
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": created.pk}))
        self.assertEqual(created.organization, self.alpha)
        self.assertEqual(created.engineer, self.engineer)

    def test_engineer_can_assign_multiple_members_during_project_creation(self):
        client_user = get_user_model().objects.create_user(
            username="creation-client",
            organization=self.alpha,
            role=get_user_model().Role.CLIENT,
        )
        site_manager = get_user_model().objects.create_user(
            username="creation-manager",
            organization=self.alpha,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:create"),
            {
                "name": "Projet avec équipe",
                "description": "Affectations immédiates",
                "location": "Douala",
                "project_date": "2026-09-10",
                "budget_amount": "10000000",
                "members": [str(client_user.pk), str(site_manager.pk)],
            },
        )

        project = Project.objects.get(name="Projet avec équipe")
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        self.assertEqual(
            set(project.memberships.values_list("user_id", flat=True)),
            {self.engineer.pk, client_user.pk, site_manager.pk},
        )

    def test_project_creation_rejects_member_from_another_organization(self):
        foreign_client = get_user_model().objects.create_user(
            username="foreign-creation-client",
            organization=self.beta,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:create"),
            {
                "name": "Projet interdit",
                "location": "Douala",
                "project_date": "2026-09-10",
                "budget_amount": "1000",
                "members": [str(foreign_client.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Project.objects.filter(name="Projet interdit").exists())
        self.assertContains(response, "Sélectionnez un choix valide")

    def test_client_can_open_client_led_project_creation(self):
        client_user = get_user_model().objects.create_user(
            username="project-client",
            organization=self.alpha,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(client_user)

        response = self.client.get(reverse("projects:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "financial_conditions")

    def test_engineer_cannot_see_project_from_other_organization(self):
        foreign_project = Project.objects.create(
            organization=self.beta,
            engineer=self.other_engineer,
            name="Projet Beta",
            location="Bafoussam",
            project_date=date.today(),
        )
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": foreign_project.pk}))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_update_project_without_changing_tenant_or_owner(self):
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse("projects:update", kwargs={"pk": self.project.pk}),
            {
                "name": "Résidence Alpha actualisée",
                "description": self.project.description,
                "location": "Douala",
                "project_date": "2026-08-20",
                "status": Project.Status.COMPLETE,
                "budget_amount": "26000000",
            },
        )

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Résidence Alpha actualisée")
        self.assertEqual(self.project.organization, self.alpha)
        self.assertEqual(self.project.engineer, self.engineer)

    def test_other_engineer_cannot_update_project(self):
        colleague = get_user_model().objects.create_user(
            username="project-colleague",
            organization=self.alpha,
            role=get_user_model().Role.ENGINEER,
        )
        self.client.force_login(colleague)

        response = self.client.get(reverse("projects:update", kwargs={"pk": self.project.pk}))

        self.assertEqual(response.status_code, 404)

    def test_project_list_search_and_status_filter(self):
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("projects:list"),
            {"q": "Résidence", "status": Project.Status.ONGOING},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.name)

    def test_project_list_can_be_sorted_by_name(self):
        Project.objects.create(
            organization=self.alpha,
            engineer=self.engineer,
            name="Atelier A",
            location="Douala",
            project_date=date.today(),
        )
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:list"), {"sort": "name_asc"})

        names = [project.name for project in response.context["page"].object_list]
        self.assertEqual(names, sorted(names))
        self.assertEqual(response.context["selected_sort"], "name_asc")

    def test_project_list_is_rendered_in_english(self):
        self.client.force_login(self.engineer)
        self.client.post(
            reverse("set_language"),
            {"language": "en", "next": reverse("projects:list")},
        )

        response = self.client.get(reverse("projects:list"))

        self.assertContains(response, "Project portfolio")
        self.assertContains(response, "View and manage your construction sites.")
        self.assertContains(response, "All statuses")

    def test_dashboard_uses_real_project_statistics(self):
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER})
        )

        self.assertEqual(response.context["project_stats"]["total"], 1)
        self.assertEqual(response.context["project_stats"]["ongoing"], 1)
        self.assertEqual(response.context["project_stats"]["budget"], Decimal("25000000"))
