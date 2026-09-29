from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership
from apps.planning.models import ProjectStage


class ProjectDetailTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Detail Corp", slug="detail-corp")
        self.engineer = get_user_model().objects.create_user(
            username="detail-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="detail-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.site_manager = get_user_model().objects.create_user(
            username="detail-manager",
            organization=self.organization,
            role=get_user_model().Role.SITE_MANAGER,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet détails",
            description="Description opérationnelle",
            location="Douala",
            project_date=date.today(),
        )
        for user in (self.client_user, self.site_manager):
            ProjectMembership.objects.create(
                organization=self.organization,
                project=self.project,
                user=user,
                project_role=(
                    ProjectMembership.Role.OWNER
                    if user.role == user.Role.CLIENT
                    else ProjectMembership.Role.SITE_MANAGER
                ),
            )

    def detail_url(self):
        return reverse("projects:detail", kwargs={"pk": self.project.pk})

    def test_all_project_tabs_are_available(self):
        self.client.force_login(self.engineer)

        for tab in (
            "overview",
            "finance",
            "stages",
            "stock",
            "documents",
            "photos",
            "comments",
            "reports",
        ):
            with self.subTest(tab=tab):
                response = self.client.get(self.detail_url(), {"tab": tab})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["selected_tab"], tab)

    def test_invalid_tab_falls_back_to_overview(self):
        self.client.force_login(self.engineer)

        response = self.client.get(self.detail_url(), {"tab": "secret-admin-tab"})

        self.assertEqual(response.context["selected_tab"], "overview")
        self.assertContains(response, "Description du projet")

    def test_client_sees_payment_capability_without_management_actions(self):
        confirm_project_ownership(
            actor=self.client_user, project=self.project, terms_accepted=True
        )
        self.client.force_login(self.client_user)

        response = self.client.get(self.detail_url(), {"tab": "finance"})

        self.assertContains(response, "Paiement autorisé")
        self.assertNotContains(response, ">Modifier</a>", html=False)
        self.assertNotContains(response, ">Membres</a>", html=False)

    def test_site_manager_sees_stage_management_capability(self):
        self.client.force_login(self.site_manager)

        response = self.client.get(self.detail_url(), {"tab": "stages"})

        self.assertContains(response, "Gestion autorisée")

    def test_assigned_user_cannot_manipulate_update_url(self):
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("projects:update", kwargs={"pk": self.project.pk}))

        self.assertEqual(response.status_code, 403)

    def test_site_manager_cannot_manipulate_members_url(self):
        self.client.force_login(self.site_manager)

        response = self.client.get(reverse("projects:members", kwargs={"pk": self.project.pk}))

        self.assertEqual(response.status_code, 403)

    def test_detail_layout_contains_mobile_responsive_navigation(self):
        self.client.force_login(self.engineer)

        response = self.client.get(self.detail_url())

        self.assertContains(response, "overflow-x-auto")
        self.assertContains(response, "sm:flex-row")

    def test_language_selector_keeps_current_project_page_and_query(self):
        self.client.force_login(self.engineer)
        current_path = f"{self.detail_url()}?tab=documents"

        page = self.client.get(current_path)
        self.assertContains(
            page,
            f'name="next" value="{current_path}"',
            html=False,
        )

        response = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": current_path},
        )
        self.assertRedirects(response, current_path, fetch_redirect_response=False)

    def test_overview_displays_progress_activity_and_role_actions(self):
        ProjectStage.objects.create(
            organization=self.organization,
            project=self.project,
            title="Fondations",
            start_date=date.today(),
            end_date=date.today(),
            status=ProjectStage.Status.ACTIVE,
            created_by=self.engineer,
        )
        self.client.force_login(self.engineer)

        response = self.client.get(self.detail_url())

        self.assertEqual(response.context["project_progress"], 50)
        self.assertContains(response, "Progression globale")
        self.assertContains(response, "Étape : Fondations")
        self.assertContains(response, "Planifier une étape")

    def test_client_gets_client_specific_quick_actions(self):
        self.client.force_login(self.client_user)

        response = self.client.get(self.detail_url())

        self.assertContains(response, "Consulter les finances")
        self.assertContains(response, "Voir les documents")
        self.assertNotContains(response, "Gérer l’équipe")
