from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class PivotReviewerAssignmentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.organization = Organization.objects.create(name="Gouvernance", slug="gouvernance")
        cls.engineer = users.objects.create_user(
            username="ingenieur-projet", organization=cls.organization,
            role=users.Role.ENGINEER,
        )
        cls.superuser = users.objects.create_superuser(
            username="verificateur-pivot", password="admin12345",
            role=users.Role.ADMIN,
        )
        cls.ordinary_admin = users.objects.create_user(
            username="admin-organisation", password="admin12345",
            organization=cls.organization, role=users.Role.ADMIN,
        )
        cls.project = Project.objects.create(
            organization=cls.organization, engineer=cls.engineer,
            name="Projet contrôlé", location="Yaoundé", project_date=date.today(),
        )

    def test_superuser_can_assign_pivot_reviewer_with_audit_trace(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("superadmin:project-pivot-reviewer-assign", kwargs={"pk": self.project.pk}),
            {"reviewer": self.superuser.pk, "confirmed": "yes"},
        )

        self.assertRedirects(
            response, reverse("superadmin:project-detail", kwargs={"pk": self.project.pk})
        )
        self.assertTrue(ProjectMembership.objects.filter(
            project=self.project, user=self.superuser,
            project_role=ProjectMembership.Role.PIVOT_REVIEWER,
        ).exists())
        self.assertTrue(AuditEvent.objects.filter(
            actor=self.superuser, action="project.pivot_reviewer_assigned",
            target_id=str(self.project.pk),
        ).exists())

    def test_organization_admin_cannot_assign_pivot_reviewer(self):
        self.client.force_login(self.ordinary_admin)
        response = self.client.post(
            reverse("superadmin:project-pivot-reviewer-assign", kwargs={"pk": self.project.pk}),
            {"reviewer": self.superuser.pk, "confirmed": "yes"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProjectMembership.objects.filter(
            project=self.project, project_role=ProjectMembership.Role.PIVOT_REVIEWER,
        ).exists())
