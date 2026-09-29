import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Invitation
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.projects.models import (
    Project,
    ProjectMembership,
    ProjectOnboarding,
    ProjectOwnership,
)
from apps.projects.services import record_actor_confirmation


class ClientLedOnboardingTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Genius", slug="genius-e17")
        self.client_user = get_user_model().objects.create_user(
            username="owner-e17",
            password="Client-owner-12345!",
            email="owner-e17@example.com",
            organization=self.organization,
            role=get_user_model().Role.CLIENT,
        )
        self.client.force_login(self.client_user)

    def create_project(self):
        response = self.client.post(
            reverse("projects:create"),
            {
                "name": "Chantier client-led",
                "description": "Construction d'une résidence",
                "location": "Douala",
                "project_date": "2026-10-01",
                "budget_amount": "12000000",
                "financial_conditions": "30 % à la commande, solde par jalons validés.",
            },
        )
        project = Project.objects.get(name="Chantier client-led")
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        return project

    def test_client_creation_initializes_owner_and_onboarding(self):
        project = self.create_project()

        self.assertIsNone(project.engineer)
        self.assertTrue(
            project.memberships.filter(
                user=self.client_user, project_role=ProjectMembership.Role.OWNER
            ).exists()
        )
        self.assertFalse(ProjectOwnership.objects.get(project=project).is_confirmed)
        onboarding = ProjectOnboarding.objects.get(project=project)
        self.assertEqual(onboarding.route, ProjectOnboarding.Route.CLIENT_LED)
        self.assertEqual(onboarding.status, ProjectOnboarding.Status.DRAFT)

    def test_owner_can_invite_contractor_and_activate_after_acceptance(self):
        project = self.create_project()
        self.client.post(
            reverse("projects:ownership-confirm", kwargs={"pk": project.pk}),
            {"terms_accepted": "on"},
        )

        response = self.client.post(
            reverse("projects:actor-invite", kwargs={"pk": project.pk}),
            {"email": "contractor-e17@example.com", "role": "contractor"},
        )
        self.assertRedirects(response, f"{project.get_absolute_url()}?tab=overview")
        invitation = Invitation.objects.get(project=project)
        self.assertEqual(invitation.project_role, ProjectMembership.Role.CONTRACTOR)
        self.assertEqual(len(mail.outbox), 1)

        # The acceptance form is tested independently; reproduce its persisted outcome
        # here so this test focuses on the activation gate.
        contractor = get_user_model().objects.create_user(
            username="contractor-e17",
            email=invitation.email,
            organization=self.organization,
            role=get_user_model().Role.CONTRACTOR,
        )
        ProjectMembership.objects.create(
            organization=self.organization,
            project=project,
            user=contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        engineer = get_user_model().objects.create_user(
            username="engineer-e17-gate", organization=self.organization,
            role=get_user_model().Role.ENGINEER,
        )
        project.engineer = engineer
        project.save(update_fields=("engineer", "updated_at"))
        record_actor_confirmation(
            user=contractor, project=project,
            project_role=ProjectMembership.Role.CONTRACTOR, accepted=True,
        )
        record_actor_confirmation(
            user=engineer, project=project,
            project_role=ProjectMembership.Role.ENGINEER, accepted=True,
        )

        response = self.client.post(
            reverse("projects:onboarding-activate", kwargs={"pk": project.pk})
        )
        self.assertRedirects(response, f"{project.get_absolute_url()}?tab=overview")
        project.refresh_from_db()
        project.onboarding.refresh_from_db()
        self.assertEqual(project.status, Project.Status.ONGOING)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.ACTIVE)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="project.onboarding_activated", target_id=str(project.pk)
            ).exists()
        )

    def test_activation_gate_reports_missing_contractor(self):
        project = self.create_project()
        self.client.post(
            reverse("projects:ownership-confirm", kwargs={"pk": project.pk}),
            {"terms_accepted": "on"},
        )

        self.client.post(reverse("projects:onboarding-activate", kwargs={"pk": project.pk}))

        project.refresh_from_db()
        self.assertEqual(project.status, Project.Status.PENDING)
        self.assertEqual(project.onboarding.status, ProjectOnboarding.Status.DRAFT)

    def test_confirmed_owner_can_invite_from_legacy_project_without_onboarding(self):
        project = self.create_project()
        self.client.post(
            reverse("projects:ownership-confirm", kwargs={"pk": project.pk}),
            {"terms_accepted": "on"},
        )
        ProjectOnboarding.objects.filter(project=project).delete()

        detail = self.client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Inviter un intervenant")
        self.assertIsNotNone(detail.context["actor_invitation_form"])

        response = self.client.post(
            reverse("projects:actor-invite", kwargs={"pk": project.pk}),
            {"email": "legacy-contractor@example.com", "role": "contractor"},
        )
        self.assertRedirects(response, f"{project.get_absolute_url()}?tab=overview")
        self.assertTrue(
            Invitation.objects.filter(
                project=project, email="legacy-contractor@example.com",
                project_role=ProjectMembership.Role.CONTRACTOR,
            ).exists()
        )

    def test_existing_engineer_logs_in_and_accepts_project_invitation(self):
        project = self.create_project()
        self.client.post(
            reverse("projects:ownership-confirm", kwargs={"pk": project.pk}),
            {"terms_accepted": "on"},
        )
        external_organization = Organization.objects.create(
            name="Bureau ingénieur externe", slug="external-engineer-office"
        )
        engineer = get_user_model().objects.create_user(
            username="existing-engineer-e17",
            password="Existing-engineer-12345!",
            email="existing-engineer-e17@example.com",
            organization=external_organization,
            role=get_user_model().Role.ENGINEER,
        )

        response = self.client.post(
            reverse("projects:actor-invite", kwargs={"pk": project.pk}),
            {"email": engineer.email, "role": "engineer"},
        )

        self.assertRedirects(response, f"{project.get_absolute_url()}?tab=overview")
        invitation = Invitation.objects.get(project=project, email=engineer.email)
        token_match = re.search(r"/comptes/invitation/([^/\s]+)/", mail.outbox[-1].body)
        self.assertIsNotNone(token_match)
        acceptance_url = reverse(
            "accounts:accept-invitation", kwargs={"token": token_match.group(1)}
        )

        self.client.logout()
        login_response = self.client.get(acceptance_url)
        self.assertRedirects(
            login_response,
            f"{reverse('accounts:login')}?next={acceptance_url}",
            fetch_redirect_response=False,
        )

        self.client.force_login(engineer)
        confirmation = self.client.get(acceptance_url)
        self.assertContains(confirmation, "Accepter l’invitation")
        accepted = self.client.post(acceptance_url)

        self.assertRedirects(accepted, project.get_absolute_url())
        invitation.refresh_from_db()
        project.refresh_from_db()
        self.assertIsNotNone(invitation.accepted_at)
        self.assertIsNone(project.engineer)
        self.assertTrue(
            project.memberships.filter(
                user=engineer,
                project_role=ProjectMembership.Role.ENGINEER,
            ).exists()
        )
