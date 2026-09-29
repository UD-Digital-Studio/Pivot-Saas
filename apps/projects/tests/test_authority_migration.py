import json
from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import ProjectDocument
from apps.finance.models import PaymentTransaction
from apps.organizations.models import Organization
from apps.projects.models import (
    Project,
    ProjectAuthorityMigrationReview,
    ProjectMembership,
    ProjectOwnership,
)


class ProjectAuthorityMigrationCommandTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.org = Organization.objects.create(name="Migration", slug="migration")
        self.operator = User.objects.create_superuser(
            username="migration-admin", password="test-password-42"
        )
        self.engineer = User.objects.create_user(
            username="migration-engineer", organization=self.org, role=User.Role.ENGINEER
        )
        self.client_a = User.objects.create_user(
            username="migration-client-a", organization=self.org, role=User.Role.CLIENT
        )
        self.client_b = User.objects.create_user(
            username="migration-client-b", organization=self.org, role=User.Role.CLIENT
        )

    def project(self, name):
        return Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name=name,
            location="Douala",
            project_date=date.today(),
        )

    def assign(self, project, user, role):
        return ProjectMembership.objects.create(
            organization=self.org, project=project, user=user, project_role=role
        )

    def run_command(self, *args):
        output = StringIO()
        call_command("migrate_project_authority", *args, stdout=output)
        return json.loads(output.getvalue()[output.getvalue().index("{") :])

    def test_dry_run_reports_without_persisting(self):
        project = self.project("Client unique")
        self.assign(project, self.client_a, ProjectMembership.Role.CONTRACTOR)
        report = self.run_command()
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["database_vendor"], "sqlite")
        self.assertEqual(report["summary"]["owner_assigned"], 1)
        self.assertFalse(ProjectOwnership.objects.filter(project=project).exists())
        self.assertFalse(AuditEvent.objects.filter(action="project.authority_migrated").exists())

    def test_apply_is_deterministic_audited_and_idempotent(self):
        project = self.project("À migrer")
        membership = self.assign(
            project, self.client_a, ProjectMembership.Role.CONTRACTOR
        )
        first = self.run_command("--apply", "--actor", self.operator.username)
        second = self.run_command("--apply", "--actor", self.operator.username)
        membership.refresh_from_db()
        ownership = ProjectOwnership.objects.get(project=project)
        self.assertEqual(membership.project_role, ProjectMembership.Role.OWNER)
        self.assertEqual(ownership.owner, self.client_a)
        self.assertTrue(ownership.is_valid)
        self.assertTrue(first["preserved"])
        self.assertTrue(second["preserved"])
        self.assertEqual(
            AuditEvent.objects.filter(
                action="project.authority_migrated", target_id=str(project.pk)
            ).count(),
            1,
        )

    def test_zero_and_multiple_clients_are_flagged_for_manual_review(self):
        empty = self.project("Sans client")
        ambiguous = self.project("Plusieurs clients")
        self.assign(ambiguous, self.client_a, ProjectMembership.Role.OWNER)
        self.assign(ambiguous, self.client_b, ProjectMembership.Role.CONTRACTOR)
        self.run_command("--apply", "--actor", self.operator.username)
        self.assertEqual(
            empty.authority_migration_review.reason,
            ProjectAuthorityMigrationReview.Reason.NO_CLIENT,
        )
        review = ambiguous.authority_migration_review
        self.assertEqual(
            review.reason, ProjectAuthorityMigrationReview.Reason.MULTIPLE_CLIENTS
        )
        self.assertEqual(set(review.candidate_user_ids), {self.client_a.pk, self.client_b.pk})
        self.assertFalse(ProjectOwnership.objects.filter(project=ambiguous, is_confirmed=True).exists())

    def test_apply_preserves_projects_files_transactions_and_histories(self):
        project = self.project("Préservation")
        self.assign(project, self.client_a, ProjectMembership.Role.OWNER)
        document = ProjectDocument.objects.create(
            organization=self.org,
            project=project,
            title="Contrat",
            file="documents/contrat.pdf",
            uploaded_by=self.engineer,
        )
        transaction = PaymentTransaction.objects.create(
            organization=self.org,
            project=project,
            user=self.client_a,
            amount=100,
            operator="mtn",
            payer_phone="670000000",
            idempotency_key="00000000-0000-0000-0000-000000000001",
        )
        report = self.run_command("--apply", "--actor", self.operator.username)
        self.assertTrue(report["preserved"])
        self.assertTrue(Project.objects.filter(pk=project.pk).exists())
        self.assertTrue(ProjectDocument.objects.filter(pk=document.pk).exists())
        self.assertTrue(PaymentTransaction.objects.filter(pk=transaction.pk).exists())
