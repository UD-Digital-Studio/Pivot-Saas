from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.audit.control_room import trust_value_metrics
from apps.finance.models import ExpenseRequest, ExpenseTechnicalOpinion
from apps.inventory.models import InventoryAnomaly, InventoryExpectedRange, StockItem
from apps.organizations.models import Organization
from apps.planning.models import (
    ProjectStage, StageProgressDeclaration, StageProgressVerification,
)
from apps.projects.models import (
    Project, ProjectActorConfirmation, ProjectMembership, ProjectOnboarding,
    ProjectOwnership, ProjectTermsVersion,
)


class ControlRoomTrustMetricsTests(TestCase):
    def test_metrics_include_confirmed_records_and_exclude_pending_ones(self):
        organization = Organization.objects.create(name="Trust E22", slug="trust-e22")
        users = get_user_model()
        engineer = users.objects.create_user(
            username="trust-engineer", organization=organization, role=users.Role.ENGINEER
        )
        owner = users.objects.create_user(
            username="trust-owner", organization=organization, role=users.Role.CLIENT
        )
        contractor = users.objects.create_user(
            username="trust-contractor", organization=organization, role=users.Role.CONTRACTOR
        )
        project = Project.objects.create(
            organization=organization, engineer=engineer, name="Projet contrôlé",
            location="Douala", project_date=date.today(), budget_amount=Decimal("5000000"),
        )
        ProjectMembership.objects.create(
            organization=organization, project=project, user=owner,
            project_role=ProjectMembership.Role.OWNER,
        )
        ProjectMembership.objects.create(
            organization=organization, project=project, user=contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        ProjectOwnership.objects.create(
            organization=organization, project=project, owner=owner, is_confirmed=True,
            confirmed_at=timezone.now(), confirmed_by=owner, terms_version="v1",
            terms_accepted=True,
        )
        ProjectOnboarding.objects.create(
            organization=organization, project=project,
            route=ProjectOnboarding.Route.CLIENT_LED,
            status=ProjectOnboarding.Status.ACTIVE,
            financial_conditions="Conditions contrôlées", initiated_by=owner,
            activated_by=owner, activated_at=timezone.now(),
        )
        terms = ProjectTermsVersion.objects.get(project=project, is_current=True)
        terms.authority_owner = owner
        terms.budget_amount = Decimal("5000000")
        terms.financial_conditions = "Conditions contrôlées"
        terms.save(update_fields=("authority_owner", "budget_amount", "financial_conditions"))
        ProjectActorConfirmation.objects.create(
            organization=organization, project=project, terms_version=terms, user=owner,
            project_role=ProjectMembership.Role.OWNER,
            status=ProjectActorConfirmation.Status.ACCEPTED,
            expires_at=timezone.now() + timedelta(days=7), responded_at=timezone.now(),
        )
        stage = ProjectStage.objects.create(
            organization=organization, project=project, title="Fondations",
            start_date=date.today(), end_date=date.today(), created_by=engineer,
        )
        declaration = StageProgressDeclaration.objects.create(
            organization=organization, stage=stage, percent=50, author=engineer,
        )
        StageProgressVerification.objects.create(
            organization=organization, stage=stage, declaration=declaration,
            percent=45, author=engineer, quantities=[], reservations=[],
        )
        verified_expense = ExpenseRequest.objects.create(
            organization=organization, project=project, author=contractor, milestone=stage,
            amount=Decimal("200000"), purpose="Ciment vérifié", beneficiary="Fournisseur",
            due_date=date.today(), status=ExpenseRequest.Status.VERIFIED,
        )
        ExpenseTechnicalOpinion.objects.create(
            organization=organization, request=verified_expense, engineer=engineer,
            decision=ExpenseTechnicalOpinion.Decision.APPROVED,
            reason="Pièces contrôlées", reviewed_status_version=1,
        )
        ExpenseRequest.objects.create(
            organization=organization, project=project, author=contractor, milestone=stage,
            amount=Decimal("900000"), purpose="Encore en revue", beneficiary="Fournisseur",
            due_date=date.today(), status=ExpenseRequest.Status.REVIEW,
        )
        rule = InventoryExpectedRange.objects.create(
            organization=organization, project=project, work_type="Fondations", unit="sac",
            minimum_quantity=Decimal("10"), maximum_quantity=Decimal("20"),
            assumptions="Plan validé", version=1, created_by=engineer,
        )
        item = StockItem.objects.create(
            organization=organization, project=project, created_by=engineer, name="Ciment",
            unit="sac", unit_price=Decimal("6500"), quantity=Decimal("5"),
            alert_threshold=Decimal("2"), expected_range=rule,
        )
        InventoryAnomaly.objects.create(
            organization=organization, project=project, expense_request=verified_expense,
            item=item, expected_range=rule, expected_range_version=rule.version,
            minimum_snapshot=Decimal("10"), maximum_snapshot=Decimal("20"),
            observed_quantity=Decimal("5"), unit_snapshot="sac",
            direction=InventoryAnomaly.Direction.BELOW,
            action=InventoryExpectedRange.OutOfRangeAction.FLAG,
            movement_ids=["auditable-movement-e22"], fingerprint="trust-e22-anomaly",
        )

        metrics = trust_value_metrics(
            date_from=timezone.localdate() - timedelta(days=1),
            date_to=timezone.localdate() + timedelta(days=1),
        )

        self.assertEqual(metrics["tracked_value"], Decimal("5000000"))
        self.assertEqual(metrics["verified_expense_amount"], Decimal("200000"))
        self.assertEqual(metrics["verified_expense_count"], 1)
        self.assertEqual(metrics["verified_milestone_count"], 1)
        self.assertEqual(metrics["anomaly_count"], 1)
        self.assertEqual(metrics["delay_sample_count"], 1)
