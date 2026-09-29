import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.finance.models import ExpenseOwnerDecision, ExpenseRequest, PaymentTransaction
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership
from apps.planning.models import (
    ProjectStage, StageDigitalVerification, StageProgressDeclaration,
    StageProgressVerification, StageVerificationReport,
)
from apps.reporting.services import (
    parse_period, project_report_projection, stage_verification_report_projection,
)


class ReportingTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Reports", slug="reports")
        self.other = Organization.objects.create(name="Other Reports", slug="other-reports")
        U = get_user_model()
        self.engineer = U.objects.create_user(
            username="report-eng", organization=self.org, role="engineer"
        )
        self.contractor = U.objects.create_user(
            username="report-contractor", organization=self.org, role="contractor"
        )
        self.foreign = U.objects.create_user(
            username="report-foreign", organization=self.other, role="engineer"
        )
        self.project = Project.objects.create(
            organization=self.org,
            engineer=self.engineer,
            name="Rapport chantier",
            location="Douala",
            project_date=date.today(),
            budget_amount=Decimal("1000000"),
        )
        self.foreign_project = Project.objects.create(
            organization=self.other,
            engineer=self.foreign,
            name="Rapport secret",
            location="Yaoundé",
            project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.org,
            project=self.project,
            user=self.contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        PaymentTransaction.objects.create(
            organization=self.org,
            project=self.project,
            user=self.engineer,
            amount=100000,
            operator="mtn",
            payer_phone="670000000",
            idempotency_key=uuid.uuid4(),
            status="success",
            provider_reference="SAFE-REF",
        )
        stage = self.stage = ProjectStage.objects.create(
            organization=self.org, project=self.project, title="Validation",
            start_date=date.today(), end_date=date.today(), created_by=self.engineer,
        )
        self.expense = ExpenseRequest.objects.create(
            organization=self.org, project=self.project, author=self.contractor,
            milestone=stage, amount=25000, purpose="Ciment", beneficiary="Fournisseur",
            due_date=date.today(), status=ExpenseRequest.Status.AUTHORIZED, status_version=5,
        )
        self.authorization = ExpenseOwnerDecision.objects.create(
            organization=self.org, request=self.expense, owner=self.engineer,
            decision=ExpenseOwnerDecision.Decision.APPROVED,
            decided_status_version=4, resulting_status_version=5,
        )
        self.expense_payment = PaymentTransaction.objects.create(
            organization=self.org, project=self.project, user=self.engineer,
            expense_request=self.expense, owner_decision=self.authorization,
            amount=25000, operator="orange", payer_phone="690000000",
            idempotency_key=uuid.uuid4(), status=PaymentTransaction.Status.SUCCESS,
            provider_reference="MESOMB-ACCOUNTED", completed_at=timezone.now(),
        )
        self.declaration = StageProgressDeclaration.objects.create(
            organization=self.org, stage=stage, author=self.engineer, percent=80,
        )
        self.verification = StageProgressVerification.objects.create(
            organization=self.org, stage=stage, author=self.engineer, percent=60,
        )

    def test_period_is_typed_and_validated(self):
        start, end = parse_period("2026-01-01", "2026-01-31")
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 1, 31))
        with self.assertRaises(ValidationError):
            parse_period("2026-02-01", "2026-01-01")

    def test_projection_is_read_only_and_exact(self):
        before = PaymentTransaction.objects.count()
        data = project_report_projection(project=self.project)
        self.assertEqual(data["totals"]["paid"], Decimal("125000"))
        self.assertEqual(PaymentTransaction.objects.count(), before)
        self.assertEqual(data["expense_requests"].count(), 1)
        self.assertEqual(data["expense_authorizations"].count(), 1)
        self.assertEqual(data["payment_attempts"].count(), 1)
        self.assertEqual(data["accounted_payments"].count(), 1)
        self.assertEqual(data["declared_stage_progress"], 80)
        self.assertEqual(data["verified_stage_progress"], 60)

    def test_center_only_lists_accessible_projects(self):
        self.client.force_login(self.engineer)
        response = self.client.get(reverse("reporting:center"))
        self.assertContains(response, self.project.name)
        self.assertNotContains(response, self.foreign_project.name)

    def test_pdf_is_generated_for_accessible_project(self):
        self.client.force_login(self.engineer)
        response = self.client.get(reverse("reporting:pdf", kwargs={"pk": self.project.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_csv_contains_persisted_filtered_data_without_secrets(self):
        self.client.force_login(self.engineer)
        response = self.client.get(
            reverse("reporting:csv", kwargs={"pk": self.project.pk}),
            {"date_from": date.today().isoformat()},
        )
        content = response.content.decode("utf-8-sig")
        self.assertIn("SAFE-REF", content)
        self.assertIn("Demande de dépense", content)
        self.assertIn("Autorisation propriétaire", content)
        self.assertIn("Tentative de paiement", content)
        self.assertIn("Succès comptabilisé", content)
        self.assertIn("Progression déclarée", content)
        self.assertIn("Progression vérifiée", content)
        self.assertNotIn("secret", content.lower())

    def test_foreign_report_is_404(self):
        self.client.force_login(self.engineer)
        self.assertEqual(
            self.client.get(
                reverse("reporting:pdf", kwargs={"pk": self.foreign_project.pk})
            ).status_code,
            404,
        )

    def complete_three_level_chain(self):
        digital = StageDigitalVerification.objects.create(
            organization=self.org, declaration=self.declaration,
            initiated_by=self.engineer, result=StageDigitalVerification.Result.PASSED,
            checks={"preuve": True, "chronologie": True},
            examined_items={"evidence": {}},
        )
        self.verification.declaration = self.declaration
        self.verification.digital_verification = digital
        self.verification.quantities = [{"label": "Béton", "quantity": 10, "unit": "m3"}]
        self.verification.reservations = [{"description": "Retouche", "status": "ouverte"}]
        self.verification.logical_signature = "signature-technique"
        self.verification.signed_at = timezone.now()
        self.verification.save()

    def test_stage_verification_pdf_has_stable_unique_reference(self):
        self.complete_three_level_chain()
        self.client.force_login(self.engineer)
        url = reverse("reporting:stage-verification-pdf", kwargs={
            "project_pk": self.project.pk, "stage_pk": self.stage.pk,
        })
        first = self.client.get(url)
        second = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first["Content-Type"], "application/pdf")
        self.assertTrue(first.content.startswith(b"%PDF"))
        self.assertEqual(StageVerificationReport.objects.count(), 1)
        report = StageVerificationReport.objects.get()
        self.assertTrue(report.reference.startswith("PIVOT-VRF-"))
        self.assertIn(report.reference, first["Content-Disposition"])
        self.assertIn(report.reference, second["Content-Disposition"])

    def test_stage_verification_projection_exposes_three_levels(self):
        self.complete_three_level_chain()
        data = stage_verification_report_projection(actor=self.engineer, stage=self.stage)
        self.assertEqual(data["digital"].result, "passed")
        self.assertEqual(data["technical"].percent, 60)
        self.assertIsNone(data["site"])
        self.assertEqual(data["reservations"][0]["description"], "Retouche")

    def test_stage_verification_pdf_obeys_project_permissions(self):
        self.complete_three_level_chain()
        self.client.force_login(self.foreign)
        response = self.client.get(reverse("reporting:stage-verification-pdf", kwargs={
            "project_pk": self.project.pk, "stage_pk": self.stage.pk,
        }))
        self.assertEqual(response.status_code, 404)
