from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.forms import InvitationAcceptanceForm
from apps.accounts.models import Invitation
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership, ProjectOnboarding


class PivotLedOnboardingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Concierge Org", slug="concierge-org")
        self.superuser = get_user_model().objects.create_superuser(
            username="pivot-concierge", password="Pivot-admin-12345!",
            email="pivot@example.com",
        )
        self.client.force_login(self.superuser)

    def create_concierge_project(self):
        response = self.client.post(
            reverse("superadmin:pivot-onboarding-create"),
            {
                "organization": self.organization.pk,
                "name": "Projet concierge",
                "description": "Dossier préparé par PIVOT",
                "location": "Douala",
                "project_date": "2026-12-01",
                "budget_amount": "15000000",
                "financial_conditions": "Décaissement par jalons confirmés.",
                "owner_email": "owner-pivot@example.com",
                "stage_title": "Études préliminaires",
                "stage_start_date": "2026-12-01",
                "stage_end_date": "2026-12-15",
                "stage_estimated_cost": "1000000",
                "document_title": "Note initiale",
                "document_file": SimpleUploadedFile(
                    "note.pdf", b"%PDF-1.4 concierge", content_type="application/pdf"
                ),
            },
        )
        project = Project.objects.get(name="Projet concierge")
        self.assertRedirects(
            response, reverse("superadmin:project-detail", kwargs={"pk": project.pk})
        )
        return project

    def test_pivot_prepares_project_stage_document_and_owner_invitation(self):
        project = self.create_concierge_project()

        self.assertEqual(project.onboarding.route, ProjectOnboarding.Route.PIVOT_LED)
        self.assertEqual(project.status, Project.Status.PENDING)
        self.assertIsNone(project.engineer)
        self.assertEqual(project.stages.count(), 1)
        self.assertEqual(project.documents.count(), 1)
        invitation = Invitation.objects.get(project=project)
        self.assertEqual(invitation.project_role, ProjectMembership.Role.OWNER)
        actions = set(
            AuditEvent.objects.filter(target_id=str(project.pk)).values_list("action", flat=True)
        )
        self.assertTrue(
            {
                "project.pivot_onboarding_created",
                "project.pivot_stage_prepared",
                "project.pivot_document_prepared",
                "project.pivot_invitation_sent",
            }.issubset(actions)
        )

    def test_client_must_personally_confirm_pivot_preparation(self):
        project = self.create_concierge_project()
        invitation = Invitation.objects.get(project=project, role=get_user_model().Role.CLIENT)
        form = InvitationAcceptanceForm(
            {
                "username": "pivot-led-owner",
                "password1": "N7!SecureConciergePass",
                "password2": "N7!SecureConciergePass",
            },
            invitation=invitation,
        )
        self.assertTrue(form.is_valid(), form.errors)
        owner = form.save()
        self.client.force_login(owner)

        detail = self.client.get(reverse("projects:detail", kwargs={"pk": project.pk}))
        self.assertContains(detail, "Confirmer le dossier")
        self.assertFalse(project.ownership.is_confirmed)

        self.client.post(
            reverse("projects:contractor-onboarding-confirm", kwargs={"pk": project.pk}),
            {
                "confirm_project": "on",
                "confirm_ownership": "on",
                "confirm_contractor": "on",
                "confirm_conditions": "on",
            },
        )
        project.refresh_from_db()
        self.assertTrue(project.ownership.is_valid)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.READY)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="project.pivot_onboarding_confirmed", target_id=str(project.pk)
            ).exists()
        )

    def test_dashboard_exposes_pivot_led_acquisition_kpi(self):
        self.create_concierge_project()
        response = self.client.get(reverse("superadmin:dashboard"))
        self.assertEqual(response.context["acquisition_routes"]["pivot_led"], 1)
        self.assertContains(response, "PIVOT-led")
