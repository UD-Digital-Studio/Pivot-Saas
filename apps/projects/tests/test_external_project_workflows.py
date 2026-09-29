from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseRequest, ExpenseTechnicalOpinion
from apps.inventory.models import StockItem
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership


class ExternalProjectWorkflowValidationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.project_organization = Organization.objects.create(
            name="Organisation chantier", slug="external-workflow-project"
        )
        self.external_organization = Organization.objects.create(
            name="Bureau externe", slug="external-workflow-office"
        )
        self.owner = User.objects.create_user(
            username="external-owner",
            organization=self.project_organization,
            role=User.Role.CLIENT,
        )
        self.contractor = User.objects.create_user(
            username="external-contractor",
            organization=self.external_organization,
            role=User.Role.CONTRACTOR,
        )
        self.site_manager = User.objects.create_user(
            username="external-site-manager",
            organization=self.external_organization,
            role=User.Role.SITE_MANAGER,
        )
        self.engineer = User.objects.create_user(
            username="external-engineer",
            organization=self.external_organization,
            role=User.Role.ENGINEER,
        )
        self.outsider = User.objects.create_user(
            username="external-outsider",
            organization=self.external_organization,
            role=User.Role.ENGINEER,
        )
        self.project = Project.objects.create(
            organization=self.project_organization,
            name="Chantier partagé",
            location="Yaoundé",
            project_date=date.today(),
        )
        for user, role in (
            (self.owner, ProjectMembership.Role.OWNER),
            (self.contractor, ProjectMembership.Role.CONTRACTOR),
            (self.site_manager, ProjectMembership.Role.SITE_MANAGER),
            (self.engineer, ProjectMembership.Role.ENGINEER),
        ):
            ProjectMembership.objects.create(
                organization=self.project_organization,
                project=self.project,
                user=user,
                project_role=role,
            )
        self.stage = ProjectStage.objects.create(
            organization=self.project_organization,
            project=self.project,
            created_by=self.engineer,
            title="Fondations",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=10),
        )

    def test_external_project_roles_validate_all_core_contributions(self):
        evidence = EvidenceRecord(
            organization=self.project_organization,
            project=self.project,
            stage=self.stage,
            author=self.site_manager,
            evidence_type=EvidenceRecord.Type.PHOTO,
            title="Photo terrain",
        )
        evidence.full_clean()

        expense = ExpenseRequest(
            organization=self.project_organization,
            project=self.project,
            author=self.contractor,
            milestone=self.stage,
            amount=Decimal("100000"),
            purpose="Achat de ciment",
            beneficiary="Fournisseur",
            due_date=date.today() + timedelta(days=2),
        )
        expense.full_clean()
        expense.save()

        opinion = ExpenseTechnicalOpinion(
            organization=self.project_organization,
            request=expense,
            engineer=self.engineer,
            decision=ExpenseTechnicalOpinion.Decision.APPROVED,
            reason="Dépense techniquement justifiée",
            reviewed_status_version=expense.status_version,
        )
        opinion.full_clean()

        stock = StockItem(
            organization=self.project_organization,
            project=self.project,
            name="Ciment",
            unit="sac",
            unit_price=Decimal("6500"),
            quantity=Decimal("20"),
            created_by=self.site_manager,
        )
        stock.full_clean()

    def test_unassigned_external_user_remains_rejected(self):
        evidence = EvidenceRecord(
            organization=self.project_organization,
            project=self.project,
            author=self.outsider,
            evidence_type=EvidenceRecord.Type.PHOTO,
            title="Preuve non autorisée",
        )
        with self.assertRaises(ValidationError):
            evidence.full_clean()

        stage = ProjectStage(
            organization=self.project_organization,
            project=self.project,
            created_by=self.outsider,
            title="Étape étrangère",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            stage.full_clean()
