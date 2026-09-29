from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpenseRequest, ExpenseRequestAttachment, ExpenseRequestTransition, ExpenseTechnicalOpinion, PaymentTransaction
from apps.finance.services import attach_expense_evidence, create_expense_request, decide_expense_by_owner, submit_expense_technical_opinion, transition_expense_request
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership


class ExpenseRequestTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Dépenses", slug="depenses")
        self.engineer = User.objects.create_user(username="expense-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.contractor = User.objects.create_user(username="expense-contractor", organization=self.organization, role=User.Role.CONTRACTOR)
        self.owner = User.objects.create_user(username="expense-owner", organization=self.organization, role=User.Role.CLIENT)
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Projet dépenses", location="Douala", project_date=date.today())
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.contractor, project_role=ProjectMembership.Role.CONTRACTOR)
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.owner, project_role=ProjectMembership.Role.OWNER)
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        self.milestone = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Fondations", start_date=date.today(), end_date=date.today() + timedelta(days=10), created_by=self.engineer)

    def data(self, mode="draft"):
        return {"amount": 150000, "currency": "xaf", "purpose": "Achat de ciment", "beneficiary": "Fournisseur ABC", "milestone": self.milestone, "due_date": date.today() + timedelta(days=3), "create_mode": mode}

    def test_contractor_creates_complete_structured_draft_without_payment(self):
        request = create_expense_request(actor=self.contractor, project=self.project, data=self.data())
        self.assertEqual(request.status, ExpenseRequest.Status.DRAFT)
        self.assertEqual(request.author, self.contractor)
        self.assertEqual(request.milestone, self.milestone)
        self.assertEqual(request.currency, "XAF")
        self.assertEqual(PaymentTransaction.objects.count(), 0)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.created", target_id=str(request.pk)).exists())

    def test_create_and_submit_is_audited_but_never_pays(self):
        request = create_expense_request(actor=self.contractor, project=self.project, data=self.data("submitted"))
        self.assertEqual(request.status, ExpenseRequest.Status.SUBMITTED)
        self.assertEqual(request.status_version, 2)
        self.assertEqual(request.transitions.count(), 1)
        self.assertEqual(PaymentTransaction.objects.count(), 0)
        transition = request.transitions.get()
        self.assertEqual(transition.actor, self.contractor)
        self.assertIsNotNone(transition.created_at)
        self.assertTrue(transition.reason)
        self.assertEqual(transition.status_version, request.status_version)

    def test_full_lifecycle_uses_authorized_atomic_transitions(self):
        request = create_expense_request(actor=self.contractor, project=self.project, data=self.data("submitted"))
        quote = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, author=self.contractor,
            evidence_type=EvidenceRecord.Type.QUOTE, title="Devis ciment",
        )
        attach_expense_evidence(
            actor=self.contractor, expense_request=request,
            document_type=ExpenseRequestAttachment.DocumentType.QUOTE, evidence=quote,
        )
        for actor, target in (
            (self.contractor, ExpenseRequest.Status.EVIDENCE),
            (self.contractor, ExpenseRequest.Status.REVIEW),
        ):
            request = transition_expense_request(actor=actor, expense_request=request, target_status=target, expected_version=request.status_version)
        opinion, request = submit_expense_technical_opinion(
            actor=self.engineer, expense_request=request,
            decision=ExpenseTechnicalOpinion.Decision.APPROVED,
            reason="Conforme à la réalité terrain", expected_version=request.status_version,
        )
        _, request = decide_expense_by_owner(
            actor=self.owner, expense_request=request, decision="approved", reason="Budget validé",
            expected_version=request.status_version,
        )
        request = transition_expense_request(actor=self.owner, expense_request=request, target_status=ExpenseRequest.Status.CLOSED, expected_version=request.status_version)
        self.assertEqual(request.status, ExpenseRequest.Status.CLOSED)
        self.assertEqual(ExpenseRequestTransition.objects.filter(request=request).count(), 6)
        self.assertEqual(PaymentTransaction.objects.count(), 0)

    def test_wrong_role_and_stale_transition_are_rejected(self):
        with self.assertRaises(PermissionDenied):
            create_expense_request(actor=self.engineer, project=self.project, data=self.data())
        request = create_expense_request(actor=self.contractor, project=self.project, data=self.data("submitted"))
        request = transition_expense_request(actor=self.contractor, expense_request=request, target_status=ExpenseRequest.Status.EVIDENCE, expected_version=request.status_version)
        with self.assertRaises(ValidationError):
            transition_expense_request(actor=self.contractor, expense_request=request, target_status=ExpenseRequest.Status.REVIEW, expected_version=request.status_version - 1)

    def test_rejection_requires_reason_in_http_form(self):
        from apps.finance.forms import ExpenseTransitionForm
        form = ExpenseTransitionForm({"target_status": "rejected", "expected_version": 1, "reason": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("reason", form.errors)
