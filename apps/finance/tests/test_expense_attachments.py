from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseRequest, ExpenseRequestAttachment, PaymentTransaction
from apps.finance.services import (
    attach_expense_evidence,
    create_expense_request,
    expense_dossier_is_complete,
    missing_expense_documents,
    reject_expense_attachment,
    replace_expense_attachment,
    required_expense_documents,
    transition_expense_request,
)
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership


class ExpenseAttachmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Justificatifs", slug="justificatifs")
        self.engineer = User.objects.create_user(
            username="attachment-engineer", organization=self.organization, role=User.Role.ENGINEER
        )
        self.contractor = User.objects.create_user(
            username="attachment-contractor", organization=self.organization, role=User.Role.CONTRACTOR
        )
        self.owner = User.objects.create_user(
            username="attachment-owner", organization=self.organization, role=User.Role.CLIENT
        )
        self.project = Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Chantier pièces",
            location="Douala", project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.organization, project=self.project, user=self.contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        ProjectMembership.objects.create(
            organization=self.organization, project=self.project, user=self.owner,
            project_role=ProjectMembership.Role.OWNER,
        )
        self.stage = ProjectStage.objects.create(
            organization=self.organization, project=self.project, title="Fondations",
            start_date=date.today(), end_date=date.today() + timedelta(days=10), created_by=self.engineer,
        )

    def request(self, expense_type=ExpenseRequest.Type.MATERIAL, amount=100000):
        return create_expense_request(
            actor=self.contractor, project=self.project,
            data={
                "expense_type": expense_type, "amount": amount, "currency": "XAF",
                "purpose": "Approvisionnement", "beneficiary": "Fournisseur",
                "milestone": self.stage, "due_date": date.today() + timedelta(days=3),
                "create_mode": "submitted",
            },
        )

    def evidence(self, evidence_type, title="Pièce"):
        return EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, author=self.contractor,
            evidence_type=evidence_type, title=title,
        )

    def attach(self, request, document_type, evidence_type):
        return attach_expense_evidence(
            actor=self.contractor, expense_request=request, document_type=document_type,
            evidence=self.evidence(evidence_type),
        )

    def test_required_documents_depend_on_type_and_amount(self):
        material = self.request()
        self.assertEqual(required_expense_documents(material), {"quote", "invoice"})
        expensive = self.request(amount=Decimal("500000"))
        self.assertEqual(required_expense_documents(expensive), {"quote", "invoice", "delivery_note"})
        labor = self.request(expense_type=ExpenseRequest.Type.LABOR)
        self.assertEqual(required_expense_documents(labor), {"quote", "field_evidence"})

    def test_missing_documents_are_explicit_and_completion_uses_active_pieces(self):
        request = self.request()
        self.assertEqual(missing_expense_documents(request), {"quote", "invoice"})
        self.attach(request, "quote", EvidenceRecord.Type.QUOTE)
        self.assertEqual(missing_expense_documents(request), {"invoice"})
        self.attach(request, "invoice", EvidenceRecord.Type.INVOICE)
        self.assertTrue(expense_dossier_is_complete(request))
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_wrong_evidence_type_and_cross_project_evidence_are_rejected(self):
        request = self.request()
        with self.assertRaises(ValidationError):
            self.attach(request, "invoice", EvidenceRecord.Type.PHOTO)
        other = Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Autre chantier",
            location="Yaoundé", project_date=date.today(),
        )
        ProjectMembership.objects.create(
            organization=self.organization, project=other, user=self.contractor,
            project_role=ProjectMembership.Role.CONTRACTOR,
        )
        foreign = EvidenceRecord.objects.create(
            organization=self.organization, project=other, author=self.contractor,
            evidence_type=EvidenceRecord.Type.QUOTE, title="Devis étranger",
        )
        with self.assertRaises(ValidationError):
            attach_expense_evidence(
                actor=self.contractor, expense_request=request, document_type="quote", evidence=foreign
            )

    def test_incomplete_dossier_cannot_enter_review(self):
        request = self.request()
        request = transition_expense_request(
            actor=self.contractor, expense_request=request, target_status=ExpenseRequest.Status.EVIDENCE,
            expected_version=request.status_version,
        )
        with self.assertRaises(ValidationError):
            transition_expense_request(
                actor=self.contractor, expense_request=request, target_status=ExpenseRequest.Status.REVIEW,
                expected_version=request.status_version,
            )
        self.attach(request, "quote", EvidenceRecord.Type.QUOTE)
        self.attach(request, "invoice", EvidenceRecord.Type.INVOICE)
        request = transition_expense_request(
            actor=self.contractor, expense_request=request, target_status=ExpenseRequest.Status.REVIEW,
            expected_version=request.status_version,
        )
        self.assertEqual(request.status, ExpenseRequest.Status.REVIEW)

    def test_rejection_and_replacement_preserve_full_history(self):
        request = self.request()
        attachment = self.attach(request, "quote", EvidenceRecord.Type.QUOTE)
        reject_expense_attachment(actor=self.engineer, attachment=attachment, reason="Montant illisible")
        attachment.refresh_from_db()
        self.assertEqual(attachment.status, ExpenseRequestAttachment.Status.REJECTED)
        self.assertIn("quote", missing_expense_documents(request))

        replacement = replace_expense_attachment(
            actor=self.contractor, attachment=attachment,
            replacement_evidence=self.evidence(EvidenceRecord.Type.QUOTE, "Devis corrigé"),
            reason="Version lisible",
        )
        attachment.refresh_from_db()
        self.assertEqual(attachment.status, ExpenseRequestAttachment.Status.REPLACED)
        self.assertEqual(attachment.replaced_by, replacement)
        self.assertEqual(request.attachments.count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.attachment_rejected").exists())
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.attachment_replaced").exists())

    def test_permissions_follow_project_roles(self):
        request = self.request()
        invoice = self.evidence(EvidenceRecord.Type.INVOICE)
        with self.assertRaises(PermissionDenied):
            attach_expense_evidence(
                actor=self.owner, expense_request=request, document_type="invoice", evidence=invoice
            )
        attachment = self.attach(request, "invoice", EvidenceRecord.Type.INVOICE)
        with self.assertRaises(PermissionDenied):
            reject_expense_attachment(actor=self.contractor, attachment=attachment, reason="Non")
