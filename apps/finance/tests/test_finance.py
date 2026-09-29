import os
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.finance.gateways import (
    FakePaymentGateway,
    GatewayResult,
    MeSombGateway,
    TimeoutPaymentOperation,
)
from apps.finance.models import PaymentTransaction, Withdrawal
from apps.finance.services import (
    expire_stale_payment,
    financial_totals,
    initiate_payment,
    reconcile_payment,
    request_withdrawal,
)
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership


class FinanceTests(TestCase):
    def setUp(self):
        gateway_patcher = patch(
            "apps.finance.services.configured_gateway", return_value=FakePaymentGateway()
        )
        gateway_patcher.start()
        self.addCleanup(gateway_patcher.stop)
        self.org = Organization.objects.create(name="Finance", slug="finance")
        U = get_user_model()
        self.eng = U.objects.create_user(username="fin-eng", organization=self.org, role="engineer")
        self.client = U.objects.create_user(
            username="fin-client", organization=self.org, role="client"
        )
        self.project = Project.objects.create(
            organization=self.org,
            engineer=self.eng,
            name="Finance project",
            location="Dla",
            project_date=date.today(),
            budget_amount=Decimal("1000"),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            project_role=ProjectMembership.Role.OWNER,
        )
        confirm_project_ownership(
            actor=self.client, project=self.project, terms_accepted=True
        )

    def test_totals_zero_partial_complete_and_withdrawal(self):
        self.assertEqual(financial_totals(self.project)["paid"], 0)
        PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=600,
            operator="mtn",
            payer_phone="670000000",
            idempotency_key=uuid.uuid4(),
            status="success",
        )
        Withdrawal.objects.create(
            organization=self.org,
            project=self.project,
            amount=100,
            reason="Matériel",
            requested_by=self.eng,
            status="accounted",
        )
        totals = financial_totals(self.project)
        self.assertEqual(totals["paid"], 600)
        self.assertEqual(totals["available"], 500)
        self.assertEqual(totals["remaining"], 400)

    def test_payment_is_idempotent(self):
        key = uuid.uuid4()
        first, created = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=200,
            operator="mtn",
            phone="670000000",
            idempotency_key=key,
        )
        second, again = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=200,
            operator="mtn",
            phone="670000000",
            idempotency_key=key,
        )
        self.assertTrue(created)
        self.assertFalse(again)
        self.assertEqual(first, second)
        self.assertEqual(financial_totals(self.project)["paid"], 200)

    def test_fake_gateway_all_statuses(self):
        for status in ("success", "failed", "expired", "pending"):
            self.assertEqual(
                FakePaymentGateway(status)
                .collect(amount=1, operator="x", phone="x", reference="x")
                .status,
                status,
            )

    def test_mesomb_reads_environment_without_network(self):
        gateway = MeSombGateway()
        self.assertIsInstance(gateway.application_key, str)

    @patch.dict(
        os.environ,
        {
            "MESOMB_APPLICATION_KEY": "app",
            "MESOMB_ACCESS_KEY": "access",
            "MESOMB_SECRET_KEY": "secret",
        },
    )
    @patch("apps.finance.gateways.TimeoutPaymentOperation")
    def test_mesomb_translates_collect_and_redacts_response(self, operation):
        response = Mock(reference="MESOMB-1")
        response.transaction.status = "SUCCESS"
        response.is_transaction_success.return_value = True
        operation.return_value.make_collect.return_value = response
        result = MeSombGateway().collect(
            amount=100, operator="mtn", phone="670000000", reference="local-1"
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.redacted, {"provider": "mesomb", "status": "SUCCESS"})
        operation.return_value.make_collect.assert_called_once_with(
            payer="670000000",
            amount=100,
            service="MTN",
            country="CM",
            currency="XAF",
            trx_id="local-1",
            mode="asynchronous",
        )

    @patch.dict(
        os.environ,
        {
            "MESOMB_APPLICATION_KEY": "app",
            "MESOMB_ACCESS_KEY": "access",
            "MESOMB_SECRET_KEY": "secret",
        },
    )
    @patch("apps.finance.gateways.TimeoutPaymentOperation")
    def test_mesomb_handles_async_response_without_transaction(self, operation):
        operation.return_value.make_collect.side_effect = TypeError("transaction is null")
        operation.return_value.last_response_data = {
            "success": False,
            "status": "FAILED",
            "transaction": None,
            "code": "provider_rejected",
        }

        result = MeSombGateway().collect(
            amount=100, operator="orange", phone="690000000", reference="local-async"
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reference, "local-async")
        self.assertEqual(result.redacted["status"], "FAILED")

    def test_provider_error_keeps_transaction_pending_and_reconcilable(self):
        gateway = Mock()
        gateway.collect.side_effect = OSError("secret network detail")
        tx, _ = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=100,
            operator="mtn",
            phone="670000000",
            idempotency_key=uuid.uuid4(),
            gateway=gateway,
        )
        self.assertEqual(tx.status, "pending")
        self.assertEqual(tx.raw_response_redacted, {"error": "provider_unavailable"})

    def test_payment_records_real_provider_and_reconciles_pending_status(self):
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult(
            "pending", "MESOMB-PENDING-1", {"provider": "mesomb", "status": "PENDING"}
        )
        tx, _ = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=100,
            operator="mtn",
            phone="670000000",
            idempotency_key=uuid.uuid4(),
            gateway=gateway,
        )
        self.assertEqual(tx.provider, "mesomb")
        self.assertEqual(tx.status, PaymentTransaction.Status.PENDING)
        gateway.query.return_value = GatewayResult(
            "success", "MESOMB-PENDING-1", {"provider": "mesomb", "status": "SUCCESS"}
        )
        tx, changed = reconcile_payment(actor=self.client, transaction_id=tx.pk, gateway=gateway)
        self.assertTrue(changed)
        self.assertEqual(tx.status, PaymentTransaction.Status.SUCCESS)
        self.assertIsNotNone(tx.completed_at)

    def test_reconciliation_uses_external_source_when_mesomb_reference_is_missing(self):
        tx = PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=100,
            operator="orange",
            payer_phone="690000000",
            provider="mesomb",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.PENDING,
        )
        tx.provider_reference = str(tx.pk)
        tx.save(update_fields=("provider_reference",))
        gateway = Mock()
        gateway.query.return_value = GatewayResult(
            "cancelled", str(tx.pk), {"provider": "mesomb", "status": "CANCELLED"}
        )
        tx, changed = reconcile_payment(
            actor=self.client, transaction_id=tx.pk, gateway=gateway
        )
        self.assertTrue(changed)
        self.assertEqual(tx.status, PaymentTransaction.Status.CANCELLED)
        gateway.query.assert_called_once_with(reference=str(tx.pk), source="EXTERNAL")

    def test_second_attempt_is_blocked_while_first_payment_is_uncertain(self):
        gateway = Mock(provider="mesomb")
        gateway.collect.return_value = GatewayResult(
            "pending", "MESOMB-UNCERTAIN", {"provider": "mesomb", "status": "PENDING"}
        )
        first, created = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=100,
            operator="mtn",
            phone="670000000",
            idempotency_key=uuid.uuid4(),
            gateway=gateway,
        )
        second, created_again = initiate_payment(
            actor=self.client,
            project=self.project,
            amount=200,
            operator="orange",
            phone="690000000",
            idempotency_key=uuid.uuid4(),
            gateway=gateway,
        )
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first, second)
        self.assertEqual(gateway.collect.call_count, 1)

    @override_settings(MESOMB_CONNECT_TIMEOUT=3, MESOMB_READ_TIMEOUT=12)
    @patch("apps.finance.gateways.requests.Session.request")
    def test_mesomb_http_call_has_explicit_connect_and_read_timeouts(self, request_call):
        response = Mock(status_code=200)
        response.json.return_value = {}
        request_call.return_value = response
        operation = TimeoutPaymentOperation("app", "access", "secret")
        with patch.object(operation, "get_authorization", return_value="signature"):
            operation.execute_request("GET", "payment/transactions/check/?ids=x", datetime.now())
        self.assertEqual(request_call.call_args.kwargs["timeout"], (3, 12))

    @override_settings(MESOMB_MAX_RETRIES=2, MESOMB_RETRY_BACKOFF=0)
    @patch("apps.finance.gateways.time.sleep")
    def test_collect_retries_connect_timeout_but_not_read_timeout(self, sleep):
        gateway = MeSombGateway()
        operation = Mock()
        success = Mock(reference="REF")
        success.transaction.status = "SUCCESS"
        success.is_transaction_success.return_value = True
        operation.make_collect.side_effect = [requests.ConnectTimeout(), success]
        with patch.object(gateway, "_operation", return_value=operation):
            result = gateway.collect(amount=100, operator="mtn", phone="670000000", reference="x")
        self.assertEqual(result.status, "success")
        self.assertEqual(operation.make_collect.call_count, 2)
        operation.make_collect.reset_mock(side_effect=True)
        operation.make_collect.side_effect = requests.ReadTimeout()
        with patch.object(gateway, "_operation", return_value=operation):
            with self.assertRaises(requests.ReadTimeout):
                gateway.collect(amount=100, operator="mtn", phone="670000000", reference="x")
        self.assertEqual(operation.make_collect.call_count, 1)

    def test_automatic_reconciliation_command_processes_pending_mesomb_payments(self):
        PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=100,
            operator="mtn",
            payer_phone="670000000",
            provider="mesomb",
            provider_reference="MESOMB-COMMAND",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.PENDING,
        )
        output = StringIO()
        with patch(
            "apps.finance.management.commands.reconcile_pending_payments.reconcile_payment",
            return_value=(Mock(), True),
        ) as reconcile:
            call_command("reconcile_pending_payments", stdout=output)
        self.assertEqual(reconcile.call_count, 1)
        self.assertIn("1 paiement(s) vérifié(s)", output.getvalue())

    def test_stale_payment_without_provider_reference_is_expired_and_audited(self):
        payment = PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=100,
            operator="mtn",
            payer_phone="670000000",
            provider="mesomb",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.PENDING,
        )

        payment, changed = expire_stale_payment(
            actor=self.client,
            transaction_id=payment.pk,
            reason="Paiement ancien sans référence.",
        )

        self.assertTrue(changed)
        self.assertEqual(payment.status, PaymentTransaction.Status.EXPIRED)
        self.assertIsNotNone(payment.completed_at)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="payment.expired_stale", target_id=str(payment.pk)
            ).exists()
        )

    @override_settings(PAYMENT_PENDING_TTL_MINUTES=2)
    def test_reconciliation_command_expires_old_unreferenced_payment(self):
        payment = PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=100,
            operator="mtn",
            payer_phone="670000000",
            provider="mesomb",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.PENDING,
        )
        PaymentTransaction.objects.filter(pk=payment.pk).update(
            requested_at=timezone.now() - timedelta(minutes=3)
        )

        output = StringIO()
        call_command("reconcile_pending_payments", stdout=output)

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.EXPIRED)
        self.assertIn("1 paiement(s) expiré(s)", output.getvalue())

    @override_settings(PAYMENT_PENDING_TTL_MINUTES=2)
    def test_reconciliation_command_closes_old_referenced_payment_still_pending(self):
        payment = PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.client,
            amount=100,
            operator="mtn",
            payer_phone="670000000",
            provider="mesomb",
            provider_reference="MESOMB-OLD-PENDING",
            idempotency_key=uuid.uuid4(),
            status=PaymentTransaction.Status.PENDING,
        )
        PaymentTransaction.objects.filter(pk=payment.pk).update(
            requested_at=timezone.now() - timedelta(minutes=3)
        )

        with patch(
            "apps.finance.management.commands.reconcile_pending_payments.reconcile_payment",
            side_effect=lambda **kwargs: (
                PaymentTransaction.objects.get(pk=kwargs["transaction_id"]), False
            ),
        ):
            call_command("reconcile_pending_payments", stdout=StringIO())

        payment.refresh_from_db()
        self.assertEqual(payment.status, PaymentTransaction.Status.EXPIRED)

    def test_engineer_requests_available_withdrawal(self):
        initiate_payment(
            actor=self.client,
            project=self.project,
            amount=500,
            operator="mtn",
            phone="670000000",
            idempotency_key=uuid.uuid4(),
        )
        withdrawal = request_withdrawal(
            actor=self.eng, project=self.project, amount=200, reason="Achat"
        )
        self.assertEqual(withdrawal.status, "pending")
