from datetime import date
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from apps.finance.gateways import FakePaymentGateway
from apps.finance.services import initiate_payment
from apps.ai_assistant.policy import authorize_capability
from apps.organizations.models import Organization
from apps.projects.access import can_authorize_project_finance
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership


class RebaselineAccessSecurityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org = Organization.objects.create(name="Access A", slug="access-a")
        self.other_org = Organization.objects.create(name="Access B", slug="access-b")
        self.engineer = User.objects.create_user(
            username="access-engineer", organization=self.org, role=User.Role.ENGINEER
        )
        self.foreign_engineer = User.objects.create_user(
            username="foreign-engineer", organization=self.other_org, role=User.Role.ENGINEER
        )
        self.owner = User.objects.create_user(
            username="access-owner", organization=self.org, role=User.Role.CLIENT
        )
        self.superuser = User.objects.create_superuser(
            username="access-root", password="test-password-42"
        )
        self.project = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Projet protégé",
            location="Douala",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=self.project,
            user=self.owner,
            project_role=ProjectMembership.Role.OWNER,
        )
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)

    def test_direct_routes_hide_existing_project_outside_scope(self):
        self.client.force_login(self.foreign_engineer)
        existing = self.client.get(reverse("projects:update", args=(self.project.pk,)))
        missing = self.client.get(reverse("projects:update", args=(uuid4(),)))
        self.assertEqual(existing.status_code, 404)
        self.assertEqual(missing.status_code, 404)

    def test_owner_only_finance_cannot_be_inherited_by_engineer_or_superuser(self):
        self.assertTrue(can_authorize_project_finance(user=self.owner, project=self.project))
        self.assertFalse(can_authorize_project_finance(user=self.engineer, project=self.project))
        self.assertFalse(can_authorize_project_finance(user=self.superuser, project=self.project))
        for actor in (self.engineer, self.superuser):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                initiate_payment(
                    actor=actor,
                    project=self.project,
                    amount=100,
                    operator="mtn",
                    phone="670000000",
                    idempotency_key=uuid4(),
                    gateway=FakePaymentGateway(),
                )

    def test_unassigned_same_organization_account_gets_no_project_visibility(self):
        colleague = get_user_model().objects.create_user(
            username="unassigned-engineer", organization=self.org, role="engineer"
        )
        self.client.force_login(colleague)
        for route in ("projects:detail", "projects:members", "projects:update"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route, args=(self.project.pk,))).status_code, 404)

    def test_assistant_project_authorization_uses_contextual_role(self):
        contractor_project = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Projet entrepreneur",
            location="Yaoundé",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=contractor_project,
            user=self.owner,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        self.assertTrue(authorize_capability(self.owner, "payment.create", project=self.project))
        with self.assertRaises(PermissionDenied):
            authorize_capability(
                self.owner, "payment.create", project=contractor_project
            )
