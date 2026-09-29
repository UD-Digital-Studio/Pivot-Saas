from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.audit.models import AuditEvent
from apps.finance.gateways import FakePaymentGateway
from apps.finance.services import initiate_payment
from apps.organizations.models import Organization
from apps.projects.models import (
    Project,
    ProjectMembership,
    ProjectOwnership,
    ProjectOwnershipHistory,
)
from apps.projects.services import (
    available_status_transitions,
    change_project_owner,
    confirm_project_ownership,
    project_has_confirmed_owner,
)


class ConfirmedOwnershipTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org = Organization.objects.create(name="Ownership", slug="ownership")
        self.engineer = User.objects.create_user(
            username="owner-engineer", organization=self.org, role=User.Role.ENGINEER
        )
        self.owner = User.objects.create_user(
            username="first-owner", organization=self.org, role=User.Role.CLIENT
        )
        self.next_owner = User.objects.create_user(
            username="next-owner", organization=self.org, role=User.Role.CLIENT
        )
        self.project = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Projet ownership",
            location="Douala",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=self.project,
            user=self.owner,
            project_role=ProjectMembership.Role.OWNER,
        )

    def test_designation_does_not_automatically_confirm_owner(self):
        self.assertFalse(project_has_confirmed_owner(self.project))
        self.assertNotIn(
            Project.Status.ONGOING,
            available_status_transitions(actor=self.engineer, project=self.project),
        )

    def test_owner_confirmation_records_actor_date_terms_and_audit(self):
        ownership, created = confirm_project_ownership(
            actor=self.owner, project=self.project, terms_accepted=True
        )
        self.assertTrue(created)
        self.assertTrue(ownership.is_valid)
        self.assertEqual(ownership.confirmed_by, self.owner)
        self.assertIsNotNone(ownership.confirmed_at)
        self.assertTrue(ownership.terms_accepted)
        self.assertTrue(ownership.terms_version)
        self.assertTrue(AuditEvent.objects.filter(action="project.ownership_confirmed").exists())

    def test_non_owner_cannot_confirm(self):
        with self.assertRaises(PermissionDenied):
            confirm_project_ownership(
                actor=self.next_owner, project=self.project, terms_accepted=True
            )

    def test_financial_workflow_is_locked_until_confirmation(self):
        with self.assertRaisesMessage(ValidationError, "confirmer son ownership"):
            initiate_payment(
                actor=self.owner,
                project=self.project,
                amount=100,
                operator="mtn",
                phone="670000000",
                idempotency_key=uuid4(),
                gateway=FakePaymentGateway(),
            )

    def test_controlled_owner_change_requires_reason_and_new_confirmation(self):
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        with self.assertRaisesMessage(ValidationError, "motif"):
            change_project_owner(
                actor=self.engineer,
                project=self.project,
                new_owner=self.next_owner,
                reason="",
            )
        ownership = change_project_owner(
            actor=self.engineer,
            project=self.project,
            new_owner=self.next_owner,
            reason="Cession officielle du chantier",
        )
        self.assertEqual(ownership.owner, self.next_owner)
        self.assertFalse(ownership.is_confirmed)
        self.assertFalse(project_has_confirmed_owner(self.project))
        history = ProjectOwnershipHistory.objects.get(project=self.project)
        self.assertEqual(history.previous_owner, self.owner)
        self.assertEqual(history.new_owner, self.next_owner)
        self.assertEqual(history.actor, self.engineer)
        self.assertEqual(history.reason, "Cession officielle du chantier")

    def test_owner_can_confirm_from_project_modal_endpoint(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("projects:ownership-confirm", args=(self.project.pk,)),
            {"terms_accepted": "on"},
        )
        self.assertRedirects(response, f"{self.project.get_absolute_url()}?tab=overview")
        self.assertTrue(project_has_confirmed_owner(self.project))

    def test_engineer_can_change_owner_from_controlled_endpoint(self):
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        self.client.force_login(self.engineer)
        response = self.client.post(
            reverse("projects:owner-change", args=(self.project.pk,)),
            {"new_owner": self.next_owner.pk, "reason": "Mandat client mis à jour"},
        )
        self.assertRedirects(response, f"{self.project.get_absolute_url()}?tab=overview")
        ownership = ProjectOwnership.objects.get(project=self.project)
        self.assertEqual(ownership.owner, self.next_owner)
        self.assertFalse(ownership.is_confirmed)
