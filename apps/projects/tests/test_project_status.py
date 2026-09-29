from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership, ProjectStatusHistory
from apps.projects.services import available_status_transitions, confirm_project_ownership


class ProjectStatusTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Status Corp", slug="status-corp")
        self.engineer = get_user_model().objects.create_user(
            username="status-engineer",
            organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        self.client_user = get_user_model().objects.create_user(
            username="status-client",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet cycle",
            location="Douala",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.organization,
            project=self.project,
            user=self.client_user,
            project_role=ProjectMembership.Role.OWNER,
        )
        confirm_project_ownership(
            actor=self.client_user, project=self.project, terms_accepted=True
        )
        self.url = reverse("projects:status-update", kwargs={"pk": self.project.pk})

    def test_authorized_engineer_changes_status_with_history_and_audit(self):
        self.client.force_login(self.engineer)

        response = self.client.post(self.url, {"status": Project.Status.ONGOING})

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.ONGOING)
        history = ProjectStatusHistory.objects.get(project=self.project)
        self.assertEqual(history.previous_status, Project.Status.PENDING)
        self.assertEqual(history.new_status, Project.Status.ONGOING)
        self.assertEqual(history.actor, self.engineer)
        event = AuditEvent.objects.get(action="project.status_changed")
        self.assertEqual(event.metadata["new_status"], Project.Status.ONGOING)

    def test_unauthorized_actor_cannot_change_status(self):
        self.client.force_login(self.client_user)

        response = self.client.post(self.url, {"status": Project.Status.COMPLETE})

        self.assertEqual(response.status_code, 403)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.PENDING)
        self.assertFalse(ProjectStatusHistory.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="project.status_changed").exists())

    def test_invalid_status_is_rejected(self):
        self.client.force_login(self.engineer)

        self.client.post(self.url, {"status": "deleted"})

        self.project.refresh_from_db()
        self.assertEqual(self.project.status, Project.Status.PENDING)

    def test_completed_project_reopening_rule_is_exposed_by_service(self):
        self.project.status = Project.Status.COMPLETE
        self.project.save(update_fields=("status",))

        transitions = available_status_transitions(actor=self.engineer, project=self.project)

        self.assertEqual(transitions, (Project.Status.PENDING, Project.Status.ONGOING))

    def test_status_endpoint_is_post_only(self):
        self.client.force_login(self.engineer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_detail_displays_status_action_and_history(self):
        ProjectStatusHistory.objects.create(
            project=self.project,
            actor=self.engineer,
            previous_status=Project.Status.PENDING,
            new_status=Project.Status.ONGOING,
        )
        self.client.force_login(self.engineer)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": self.project.pk}))

        self.assertContains(response, "Changer le statut")
        self.assertContains(response, "Historique du statut")
        self.assertContains(response, "En attente → En cours")
