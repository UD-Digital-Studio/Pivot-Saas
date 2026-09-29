from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.forms import InvitationAcceptanceForm
from apps.accounts.models import Invitation
from apps.accounts.services import create_invitation
from apps.finance.services import initiate_payment
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership, ProjectOnboarding
from apps.projects.services import record_actor_confirmation


class ContractorLedOnboardingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Contractor Space", slug="contractor-e17")
        self.contractor = get_user_model().objects.create_user(
            username="contractor-owner-flow",
            password="Contractor-12345!",
            organization=self.organization,
            role=get_user_model().Role.CONTRACTOR,
        )
        self.client.force_login(self.contractor)

    def create_preliminary_project(self):
        response = self.client.post(
            reverse("projects:create"),
            {
                "name": "Workspace préliminaire",
                "description": "Proposition préparée par l'entrepreneur",
                "location": "Yaoundé",
                "project_date": "2026-11-01",
                "budget_amount": "9000000",
                "financial_conditions": "Paiement suivant les jalons acceptés par le client.",
            },
        )
        project = Project.objects.get(name="Workspace préliminaire")
        self.assertEqual(response.status_code, 302)
        return project

    def test_contractor_creates_explicit_preliminary_workspace(self):
        project = self.create_preliminary_project()

        self.assertIsNone(project.engineer)
        self.assertEqual(project.status, Project.Status.PENDING)
        self.assertEqual(project.onboarding.route, ProjectOnboarding.Route.CONTRACTOR_LED)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.DRAFT)
        self.assertTrue(
            project.memberships.filter(
                user=self.contractor, project_role=ProjectMembership.Role.CONTRACTOR
            ).exists()
        )

    def test_contractor_invites_owner_with_expiring_secure_link(self):
        project = self.create_preliminary_project()

        response = self.client.post(
            reverse("projects:actor-invite", kwargs={"pk": project.pk}),
            {"email": "future-owner@example.com", "role": "client"},
        )

        self.assertEqual(response.status_code, 302)
        invitation = Invitation.objects.get(project=project)
        self.assertEqual(invitation.project_role, ProjectMembership.Role.OWNER)
        self.assertGreater(invitation.expires_at, timezone.now())
        self.assertEqual(len(invitation.token_hash), 64)

    def test_client_accepts_and_confirms_before_finance_unlock(self):
        project = self.create_preliminary_project()
        invitation, _ = create_invitation(
            actor=self.contractor,
            email="confirmed-owner@example.com",
            role=get_user_model().Role.CLIENT,
            project=project,
            project_role=ProjectMembership.Role.OWNER,
        )
        form = InvitationAcceptanceForm(
            {
                "username": "confirmed-owner",
                "password1": "Owner-Confirmation-12345!",
                "password2": "Owner-Confirmation-12345!",
            },
            invitation=invitation,
        )
        self.assertTrue(form.is_valid(), form.errors)
        owner = form.save()
        self.client.force_login(owner)

        response = self.client.post(
            reverse("projects:contractor-onboarding-confirm", kwargs={"pk": project.pk}),
            {
                "confirm_project": "on",
                "confirm_ownership": "on",
                "confirm_contractor": "on",
                "confirm_conditions": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        project.refresh_from_db()
        project.onboarding.refresh_from_db()
        self.assertTrue(project.ownership.is_valid)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.READY)

        gateway = Mock()
        with self.assertRaisesMessage(ValidationError, "finances restent verrouillées"):
            initiate_payment(
                actor=owner,
                project=project,
                amount="1000",
                operator="mtn",
                phone="670000000",
                idempotency_key="contractor-led-locked",
                gateway=gateway,
            )
        gateway.collect.assert_not_called()

        engineer = get_user_model().objects.create_user(
            username="contractor-flow-engineer", organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        project.engineer = engineer
        project.save(update_fields=("engineer", "updated_at"))
        record_actor_confirmation(
            user=self.contractor, project=project,
            project_role=ProjectMembership.Role.CONTRACTOR, accepted=True,
        )
        record_actor_confirmation(
            user=engineer, project=project,
            project_role=ProjectMembership.Role.ENGINEER, accepted=True,
        )

        self.client.post(reverse("projects:onboarding-activate", kwargs={"pk": project.pk}))
        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ONGOING)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.ACTIVE)
