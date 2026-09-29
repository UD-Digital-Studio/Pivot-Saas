from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseRequest, ExpenseRequestAttachment, ExpenseTechnicalOpinion, PaymentTransaction
from apps.finance.services import attach_expense_evidence, create_expense_request, submit_expense_technical_opinion, transition_expense_request
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership


class ExpenseTechnicalOpinionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Avis terrain", slug="avis-terrain")
        self.engineer = User.objects.create_user(username="review-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.contractor = User.objects.create_user(username="review-contractor", organization=self.organization, role=User.Role.CONTRACTOR)
        self.owner = User.objects.create_user(username="review-owner", organization=self.organization, role=User.Role.CLIENT)
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Chantier avis", location="Douala", project_date=date.today())
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.contractor, project_role=ProjectMembership.Role.CONTRACTOR)
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.owner, project_role=ProjectMembership.Role.OWNER)
        self.stage = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Élévation", start_date=date.today(), end_date=date.today() + timedelta(days=10), created_by=self.engineer)

    def evidence(self, kind, title):
        return EvidenceRecord.objects.create(organization=self.organization, project=self.project, author=self.contractor, evidence_type=kind, title=title)

    def request_in_review(self):
        expense = create_expense_request(actor=self.contractor, project=self.project, data={
            "expense_type": ExpenseRequest.Type.OTHER, "amount": 100000, "currency": "XAF",
            "purpose": "Travaux complémentaires", "beneficiary": "Entreprise locale",
            "milestone": self.stage, "due_date": date.today() + timedelta(days=2), "create_mode": "submitted",
        })
        attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type="quote", evidence=self.evidence(EvidenceRecord.Type.QUOTE, "Devis"))
        expense = transition_expense_request(actor=self.contractor, expense_request=expense, target_status=ExpenseRequest.Status.EVIDENCE, expected_version=expense.status_version)
        return transition_expense_request(actor=self.contractor, expense_request=expense, target_status=ExpenseRequest.Status.REVIEW, expected_version=expense.status_version)

    def test_site_manager_links_delivery_work_and_progress_evidence(self):
        expense = create_expense_request(actor=self.contractor, project=self.project, data={
            "expense_type": ExpenseRequest.Type.OTHER, "amount": 100000, "currency": "XAF",
            "purpose": "Suivi terrain", "beneficiary": "Équipe", "milestone": self.stage,
            "due_date": date.today(), "create_mode": "submitted",
        })
        pairs = (
            (ExpenseRequestAttachment.DocumentType.DELIVERY_NOTE, EvidenceRecord.Type.DELIVERY_NOTE),
            (ExpenseRequestAttachment.DocumentType.WORK_EVIDENCE, EvidenceRecord.Type.PHOTO),
            (ExpenseRequestAttachment.DocumentType.PROGRESS_EVIDENCE, EvidenceRecord.Type.INSPECTION),
        )
        for document_type, evidence_type in pairs:
            attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type=document_type, evidence=self.evidence(evidence_type, document_type))
        self.assertEqual(expense.attachments.count(), 3)

    def test_approved_opinion_verifies_but_never_authorizes_or_pays(self):
        expense = self.request_in_review()
        opinion, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="approved", reason="Livraison et travaux conformes", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.VERIFIED)
        self.assertNotEqual(expense.status, ExpenseRequest.Status.AUTHORIZED)
        self.assertTrue(opinion.is_current)
        self.assertEqual(PaymentTransaction.objects.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.technical_opinion_submitted", target_id=str(opinion.pk)).exists())

    def test_conditional_opinion_is_motivated_and_preserved(self):
        expense = self.request_in_review()
        opinion, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="conditional", reason="Sous réserve du contrôle de quantité", expected_version=expense.status_version)
        self.assertEqual(opinion.decision, ExpenseTechnicalOpinion.Decision.CONDITIONAL)
        self.assertEqual(expense.status, ExpenseRequest.Status.VERIFIED)

    def test_rejected_opinion_returns_request_to_evidence(self):
        expense = self.request_in_review()
        opinion, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="rejected", reason="Travaux non constatés", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.EVIDENCE)
        self.assertTrue(opinion.is_current)

    def test_wrong_role_stale_version_and_empty_reason_are_rejected(self):
        expense = self.request_in_review()
        with self.assertRaises(PermissionDenied):
            submit_expense_technical_opinion(actor=self.contractor, expense_request=expense, decision="approved", reason="Oui", expected_version=expense.status_version)
        with self.assertRaises(ValidationError):
            submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        with self.assertRaises(ValidationError):
            submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="approved", reason="Oui", expected_version=expense.status_version - 1)

    def test_substantive_change_reopens_review_and_supersedes_opinion(self):
        expense = self.request_in_review()
        opinion, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision="approved", reason="Conforme", expected_version=expense.status_version)
        attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type="progress_evidence", evidence=self.evidence(EvidenceRecord.Type.PHOTO, "Progression actualisée"))
        expense.refresh_from_db()
        opinion.refresh_from_db()
        self.assertEqual(expense.status, ExpenseRequest.Status.EVIDENCE)
        self.assertFalse(opinion.is_current)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.review_reopened", target_id=str(expense.pk)).exists())
