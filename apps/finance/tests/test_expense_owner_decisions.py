from datetime import date, timedelta
import uuid
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import Notification
from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseOwnerDecision, ExpenseRequest, PaymentTransaction
from apps.finance.gateways import GatewayResult
from apps.finance.services import attach_expense_evidence, create_expense_request, decide_expense_by_owner, initiate_expense_payment, reconcile_payment, submit_expense_technical_opinion, transition_expense_request
from apps.inventory.models import InventoryAnomaly, InventoryExpectedRange, StockItem, StockMovement
from apps.inventory.services import assign_expected_range, record_stock_movement
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership


class ExpenseOwnerDecisionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Décision owner", slug="decision-owner")
        self.engineer = User.objects.create_user(username="owner-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.contractor = User.objects.create_user(username="owner-contractor", organization=self.organization, role=User.Role.CONTRACTOR)
        self.owner = User.objects.create_user(username="confirmed-owner", organization=self.organization, role=User.Role.CLIENT)
        self.reviewer = User.objects.create_user(username="owner-reviewer", organization=self.organization, role=User.Role.ADMIN)
        self.superuser = User.objects.create_superuser(username="owner-super", email="super-owner@pivot.test", password="pass")
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Chantier owner", location="Douala", project_date=date.today())
        for user, role in ((self.contractor, ProjectMembership.Role.CONTRACTOR), (self.owner, ProjectMembership.Role.OWNER), (self.reviewer, ProjectMembership.Role.PIVOT_REVIEWER)):
            ProjectMembership.objects.create(organization=self.organization, project=self.project, user=user, project_role=role)
        self.stage = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Fondations", start_date=date.today(), end_date=date.today() + timedelta(days=7), created_by=self.engineer)

    def verified_request(self):
        expense = create_expense_request(actor=self.contractor, project=self.project, data={
            "expense_type": ExpenseRequest.Type.OTHER, "amount": 100000, "currency": "XAF",
            "purpose": "Main courante", "beneficiary": "Prestataire", "milestone": self.stage,
            "due_date": date.today() + timedelta(days=2), "create_mode": "submitted",
        })
        quote = EvidenceRecord.objects.create(organization=self.organization, project=self.project, author=self.contractor, evidence_type=EvidenceRecord.Type.QUOTE, title="Devis owner")
        attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type="quote", evidence=quote)
        expense = transition_expense_request(actor=self.contractor, expense_request=expense, target_status="evidence", expected_version=expense.status_version)
        expense = transition_expense_request(actor=self.contractor, expense_request=expense, target_status="review", expected_version=expense.status_version)
        _, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="approved", reason="Conforme", expected_version=expense.status_version)
        return expense

    def test_only_confirmed_owner_can_authorize(self):
        expense = self.verified_request()
        for actor in (self.engineer, self.contractor, self.reviewer, self.superuser):
            with self.assertRaises(PermissionDenied):
                decide_expense_by_owner(actor=actor, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        with self.assertRaises(PermissionDenied):
            decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        decision, expense = decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="Budget disponible", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.AUTHORIZED)
        self.assertEqual(decision.owner, self.owner)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_refusal_requires_reason_and_notifies_project_actors(self):
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        expense = self.verified_request()
        with self.assertRaises(ValidationError):
            decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="rejected", reason="", expected_version=expense.status_version)
        decision, expense = decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="rejected", reason="Dépense non prioritaire", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.REJECTED)
        self.assertEqual(decision.decision, ExpenseOwnerDecision.Decision.REJECTED)
        notified = set(Notification.objects.values_list("recipient__username", flat=True))
        self.assertTrue({self.contractor.username, self.engineer.username, self.reviewer.username}.issubset(notified))
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.owner_decision", target_id=str(decision.pk)).exists())

    def test_stale_version_and_second_decision_are_blocked_atomically(self):
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        expense = self.verified_request()
        with self.assertRaises(ValidationError):
            decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version - 1)
        _, updated = decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        with self.assertRaises(ValidationError):
            decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="rejected", reason="Changement", expected_version=expense.status_version)
        self.assertEqual(ExpenseOwnerDecision.objects.filter(request=updated).count(), 1)

    def test_decision_buttons_are_visible_only_to_confirmed_owner(self):
        expense = self.verified_request()
        self.client.force_login(self.engineer)
        response = self.client.get(f"{self.project.get_absolute_url()}?tab=expenses")
        self.assertNotContains(response, "Confirmer l’autorisation")
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        self.client.force_login(self.owner)
        response = self.client.get(f"{self.project.get_absolute_url()}?tab=expenses")
        self.assertContains(response, "Confirmer l’autorisation")
        self.assertContains(response, f'name="expected_version" value="{expense.status_version}"')

    def authorized_request(self):
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        expense = self.verified_request()
        _, expense = decide_expense_by_owner(
            actor=self.owner, expense_request=expense, decision="approved",
            reason="Paiement validé", expected_version=expense.status_version,
        )
        return expense

    def inventory_deviation(self, *, action):
        item = StockItem.objects.create(
            organization=self.organization, project=self.project, name="Ciment", unit="sac",
            unit_price=6500, quantity=0, alert_threshold=2, created_by=self.engineer,
        )
        assign_expected_range(
            actor=self.engineer, item=item, work_type="Fondations", unit="sac",
            minimum_quantity=10, maximum_quantity=20,
            assumptions="Dosage prévu pour les fondations.", out_of_range_action=action,
        )
        record_stock_movement(
            actor=self.engineer, item=item, movement_type=StockMovement.Type.DELIVERED,
            source_quantity=30, source_unit="sac", conversion_factor=1,
            source_reference="BL-STOCK", reason="Réception", idempotency_key=uuid.uuid4(),
            stage=self.stage,
        )
        record_stock_movement(
            actor=self.engineer, item=item, movement_type=StockMovement.Type.CONSUMED,
            source_quantity=25, source_unit="sac", conversion_factor=1,
            source_reference="FC-STOCK", reason="Consommation", idempotency_key=uuid.uuid4(),
            stage=self.stage,
        )
        return item

    def test_mesomb_is_never_called_before_owner_authorization(self):
        expense = self.verified_request()
        gateway = Mock(provider="mesomb")
        with self.assertRaises(ValidationError):
            initiate_expense_payment(actor=self.owner, expense_request=expense, operator="mtn", phone="670000000", idempotency_key=uuid.uuid4(), gateway=gateway)
        gateway.collect.assert_not_called()

    def test_inventory_warning_is_persisted_but_does_not_decide_payment(self):
        expense = self.authorized_request()
        item = self.inventory_deviation(action=InventoryExpectedRange.OutOfRangeAction.FLAG)
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult("pending", "MESOMB-WARN", {"status": "PENDING"})
        tx, created = initiate_expense_payment(
            actor=self.owner, expense_request=expense, operator="mtn", phone="670000000",
            idempotency_key=uuid.uuid4(), gateway=gateway,
        )
        self.assertTrue(created)
        self.assertEqual(tx.status, PaymentTransaction.Status.PENDING)
        anomaly = InventoryAnomaly.objects.get(expense_request=expense, item=item)
        self.assertFalse(anomaly.blocks_payment)
        self.assertEqual(anomaly.observed_quantity, 25)

    def test_blocking_inventory_rule_stops_mesomb_and_finding_survives_new_rule(self):
        expense = self.authorized_request()
        item = self.inventory_deviation(action=InventoryExpectedRange.OutOfRangeAction.BLOCK)
        gateway = Mock(provider="mesomb")
        with self.assertRaisesMessage(ValidationError, "anomalie de stock"):
            initiate_expense_payment(
                actor=self.owner, expense_request=expense, operator="mtn", phone="670000000",
                idempotency_key=uuid.uuid4(), gateway=gateway,
            )
        gateway.collect.assert_not_called()
        original = InventoryAnomaly.objects.get(expense_request=expense, item=item)
        assign_expected_range(
            actor=self.engineer, item=item, work_type="Fondations", unit="sac",
            minimum_quantity=20, maximum_quantity=30,
            assumptions="Nouvelle hypothèse après contrôle.",
            out_of_range_action=InventoryExpectedRange.OutOfRangeAction.FLAG,
        )
        self.assertTrue(InventoryAnomaly.objects.filter(pk=original.pk).exists())
        self.assertEqual(original.maximum_snapshot, 20)

    def test_authorized_amount_beneficiary_and_distinct_references_are_server_side(self):
        expense = self.authorized_request()
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult("success", "MESOMB-REF-1", {"provider": "mesomb", "status": "SUCCESS"}, "OPERATOR-REF-1")
        tx, created = initiate_expense_payment(actor=self.owner, expense_request=expense, operator="orange", phone="690000000", idempotency_key=uuid.uuid4(), gateway=gateway)
        self.assertTrue(created)
        self.assertEqual(tx.amount, expense.amount)
        self.assertEqual(tx.beneficiary_snapshot, expense.beneficiary)
        self.assertTrue(tx.pivot_reference.startswith("PIVOT-"))
        self.assertEqual(tx.provider_reference, "MESOMB-REF-1")
        self.assertEqual(tx.operator_reference, "OPERATOR-REF-1")
        self.assertEqual(len({tx.pivot_reference, tx.provider_reference, tx.operator_reference}), 3)
        expense.refresh_from_db()
        self.assertEqual(expense.status, ExpenseRequest.Status.CLOSED)

    def test_payment_logs_hide_full_phone_and_idempotency_key(self):
        expense = self.authorized_request()
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult("pending", "MESOMB-SAFE", {"status": "PENDING"})
        secret_phone = "690123456"
        secret_key = uuid.uuid4()
        with self.assertLogs("pivot.payments", level="INFO") as captured:
            initiate_expense_payment(
                actor=self.owner, expense_request=expense, operator="orange",
                phone=secret_phone, idempotency_key=secret_key, gateway=gateway,
            )
        output = "\n".join(captured.output)
        self.assertNotIn(secret_phone, output)
        self.assertNotIn(str(secret_key), output)
        self.assertIn("*****3456", output)

    def test_pending_blocks_second_attempt_and_is_not_accounted_until_reconciliation(self):
        expense = self.authorized_request()
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult("pending", "MESOMB-PENDING", {"provider": "mesomb", "status": "PENDING"}, "OP-PENDING")
        key = uuid.uuid4()
        tx, created = initiate_expense_payment(actor=self.owner, expense_request=expense, operator="mtn", phone="670000000", idempotency_key=key, gateway=gateway)
        self.assertTrue(created)
        expense.refresh_from_db()
        self.assertEqual(expense.status, ExpenseRequest.Status.AUTHORIZED)
        same, created_again = initiate_expense_payment(actor=self.owner, expense_request=expense, operator="mtn", phone="670000000", idempotency_key=uuid.uuid4(), gateway=gateway)
        self.assertFalse(created_again)
        self.assertEqual(same.pk, tx.pk)
        self.assertEqual(expense.payment_transactions.filter(status="success").count(), 0)
        gateway.query.return_value = GatewayResult("success", "MESOMB-PENDING", {"provider": "mesomb", "status": "SUCCESS"}, "OP-FINAL")
        tx, changed = reconcile_payment(actor=self.owner, transaction_id=tx.pk, gateway=gateway)
        self.assertTrue(changed)
        expense.refresh_from_db()
        self.assertEqual(expense.status, ExpenseRequest.Status.CLOSED)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.payment_accounted", target_id=str(tx.pk)).exists())

    def test_failed_attempt_is_not_accounted_and_allows_a_new_idempotent_attempt(self):
        expense = self.authorized_request()
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult("failed", "MESOMB-FAILED", {"provider": "mesomb", "status": "FAILED"})
        first, _ = initiate_expense_payment(actor=self.owner, expense_request=expense, operator="mtn", phone="670000000", idempotency_key=uuid.uuid4(), gateway=gateway)
        expense.refresh_from_db()
        self.assertEqual(first.status, PaymentTransaction.Status.FAILED)
        self.assertEqual(expense.status, ExpenseRequest.Status.AUTHORIZED)
        gateway.collect.return_value = GatewayResult("pending", "MESOMB-RETRY", {"provider": "mesomb", "status": "PENDING"})
        second, created = initiate_expense_payment(actor=self.owner, expense_request=expense, operator="mtn", phone="670000000", idempotency_key=uuid.uuid4(), gateway=gateway)
        self.assertTrue(created)
        self.assertNotEqual(first.pk, second.pk)
