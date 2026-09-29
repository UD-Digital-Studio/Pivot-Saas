from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class ProjectModalTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Modal Corp", slug="modal-corp")
        self.engineer = get_user_model().objects.create_user(
            username="modal-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="modal-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet modal",
            location="Douala",
            project_date=date.today(),
        )

    def test_engineer_dashboard_contains_project_and_invitation_modals(self):
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("accounts:dashboard", kwargs={"role": get_user_model().Role.ENGINEER})
        )

        self.assertContains(response, 'data-modal-open="modal-project-create"')
        self.assertContains(response, 'id="modal-project-create"')
        self.assertContains(response, 'data-modal-open="modal-invitation"')
        self.assertContains(response, 'id="modal-invitation"')

    def test_project_list_uses_creation_modal(self):
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:list"))

        self.assertContains(response, 'data-modal-open="modal-project-create"')
        self.assertContains(response, f'action="{reverse("projects:create")}"')
        self.assertContains(response, "data-member-picker")
        self.assertContains(response, 'autocomplete="off"')
        self.assertNotContains(response, self.client_user.username)

    def test_member_autocomplete_searches_only_current_organization(self):
        foreign_organization = Organization.objects.create(
            name="Foreign Modal", slug="foreign-modal"
        )
        get_user_model().objects.create_user(
            username="modal-client-foreign",
            organization=foreign_organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:member-search"), {"q": "modal-client"})

        self.assertEqual(response.status_code, 200)
        usernames = [item["username"] for item in response.json()["results"]]
        self.assertEqual(usernames, [self.client_user.username])

    def test_member_autocomplete_requires_two_characters(self):
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:member-search"), {"q": "m"})

        self.assertEqual(response.json(), {"results": []})

    def test_client_cannot_enumerate_members(self):
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("projects:member-search"), {"q": "modal"})

        self.assertEqual(response.status_code, 403)

    def test_project_owner_sees_edit_and_members_modals(self):
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))

        self.assertContains(response, 'data-modal-open="modal-project-edit"')
        self.assertContains(response, 'id="modal-project-edit"')
        self.assertContains(response, 'data-modal-open="modal-project-members"')
        self.assertContains(response, 'id="modal-project-members"')

    def test_assigned_client_does_not_receive_management_modals(self):
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=self.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))

        self.assertNotContains(response, 'id="modal-project-edit"')
        self.assertNotContains(response, 'id="modal-project-members"')
