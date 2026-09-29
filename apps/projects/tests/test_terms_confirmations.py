from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.organizations.models import Organization
from apps.projects.models import (
    Project, ProjectActorConfirmation, ProjectMembership, ProjectOnboarding,
    ProjectOwnership,
)
from apps.projects.services import (
    activate_client_led_project, client_led_onboarding_missing,
    create_terms_version, record_actor_confirmation,
)


class VersionedTermsConfirmationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Terms Org", slug="terms-org")
        self.owner = User.objects.create_user(username="terms-owner", organization=self.organization, role=User.Role.CLIENT)
        self.contractor = User.objects.create_user(username="terms-contractor", organization=self.organization, role=User.Role.CONTRACTOR)
        self.engineer = User.objects.create_user(username="terms-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.project = Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Versioned project",
            location="Douala", project_date="2026-12-01", budget_amount=1000000,
        )
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.owner, project_role=ProjectMembership.Role.OWNER)
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.contractor, project_role=ProjectMembership.Role.CONTRACTOR)
        ProjectOwnership.objects.create(
            organization=self.organization, project=self.project, owner=self.owner,
            is_confirmed=True, confirmed_at=timezone.now(), confirmed_by=self.owner,
            terms_accepted=True, terms_version="v1",
        )
        ProjectOnboarding.objects.create(
            organization=self.organization, project=self.project,
            route=ProjectOnboarding.Route.CLIENT_LED,
            financial_conditions="Conditions v1", initiated_by=self.owner,
        )
        record_actor_confirmation(
            user=self.owner, project=self.project,
            project_role=ProjectMembership.Role.OWNER, accepted=True,
        )

    def test_budget_currency_conditions_and_authority_are_versioned(self):
        terms = create_terms_version(
            actor=self.owner, project=self.project, budget_amount=2000000,
            currency="EUR", financial_conditions="Conditions majeures v2",
            targeted_roles=[ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER],
        )
        self.assertEqual(terms.version, 2)
        self.assertEqual(terms.currency, "EUR")
        self.assertEqual(terms.authority_owner, self.owner)
        self.assertEqual(terms.actor_confirmations.filter(status="pending").count(), 2)

    def test_rejection_and_expiration_block_activation(self):
        create_terms_version(
            actor=self.owner, project=self.project, budget_amount=1000000,
            currency="XAF", financial_conditions="Conditions v2",
            targeted_roles=[ProjectMembership.Role.CONTRACTOR],
        )
        record_actor_confirmation(
            user=self.contractor, project=self.project,
            project_role=ProjectMembership.Role.CONTRACTOR, accepted=False,
        )
        self.assertIn("contractor_confirmation", client_led_onboarding_missing(self.project))

        confirmation = self.project.actor_confirmations.get(
            terms_version__is_current=True, user=self.engineer
        ) if self.project.actor_confirmations.filter(terms_version__is_current=True, user=self.engineer).exists() else ProjectActorConfirmation.objects.create(
            terms_version=self.project.terms_versions.get(is_current=True), project=self.project,
            organization=self.organization, user=self.engineer,
            project_role=ProjectMembership.Role.ENGINEER,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertFalse(confirmation.is_valid)
        self.assertIn("engineer_confirmation", client_led_onboarding_missing(self.project))
        with self.assertRaises(Exception):
            activate_client_led_project(actor=self.owner, project=self.project)

    def test_all_targeted_actors_can_accept_new_version(self):
        create_terms_version(
            actor=self.owner, project=self.project, budget_amount=1200000,
            currency="XAF", financial_conditions="Conditions v2",
            targeted_roles=[ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER],
        )
        for user, role in ((self.contractor, "contractor"), (self.engineer, "engineer")):
            record_actor_confirmation(user=user, project=self.project, project_role=role, accepted=True)
        missing = client_led_onboarding_missing(self.project)
        self.assertNotIn("contractor_confirmation", missing)
        self.assertNotIn("engineer_confirmation", missing)

    def test_activation_is_atomic_and_idempotent(self):
        record_actor_confirmation(
            user=self.contractor, project=self.project,
            project_role=ProjectMembership.Role.CONTRACTOR, accepted=True,
        )
        record_actor_confirmation(
            user=self.engineer, project=self.project,
            project_role=ProjectMembership.Role.ENGINEER, accepted=True,
        )
        first = activate_client_led_project(actor=self.owner, project=self.project)
        second = activate_client_led_project(actor=self.owner, project=self.project)
        self.assertEqual(first.pk, second.pk)
        from apps.audit.models import AuditEvent
        self.assertEqual(
            AuditEvent.objects.filter(
                action="project.onboarding_activated", target_id=str(self.project.pk)
            ).count(),
            1,
        )
