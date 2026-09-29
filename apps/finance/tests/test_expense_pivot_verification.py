from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.finance.models import ExpensePivotVerification, ExpenseRequest, PaymentTransaction
from apps.finance.services import (
    EXCEPTIONAL_PIVOT_CONFIRMATION,
    attach_expense_evidence,
    create_expense_request,
    decide_expense_by_owner,
    evaluate_expense_risk,
    submit_expense_pivot_verification,
    submit_expense_technical_opinion,
    transition_expense_request,
)
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership
from apps.projects.services import confirm_project_ownership


class ExpensePivotVerificationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Contrôle PIVOT", slug="controle-pivot")
        self.engineer = User.objects.create_user(username="risk-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.contractor = User.objects.create_user(username="risk-contractor", organization=self.organization, role=User.Role.CONTRACTOR)
        self.owner = User.objects.create_user(username="risk-owner", organization=self.organization, role=User.Role.CLIENT)
        self.reviewer = User.objects.create_user(username="pivot-reviewer", organization=self.organization, role=User.Role.ADMIN)
        self.superuser = User.objects.create_superuser(username="pivot-super", email="super@pivot.test", password="pass")
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Chantier à risque", location="Douala", project_date=date.today())
        for user, role in ((self.contractor, ProjectMembership.Role.CONTRACTOR), (self.owner, ProjectMembership.Role.OWNER), (self.reviewer, ProjectMembership.Role.PIVOT_REVIEWER)):
            ProjectMembership.objects.create(organization=self.organization, project=self.project, user=user, project_role=role)
        confirm_project_ownership(actor=self.owner, project=self.project, terms_accepted=True)
        self.stage = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Structure", start_date=date.today(), end_date=date.today() + timedelta(days=15), created_by=self.engineer)

    def evidence(self, kind, title, stage=None):
        return EvidenceRecord.objects.create(organization=self.organization, project=self.project, author=self.contractor, stage=stage, evidence_type=kind, title=title)

    def verified_request(self, amount=600000, opinion="approved"):
        expense = create_expense_request(actor=self.contractor, project=self.project, data={
            "expense_type": ExpenseRequest.Type.MATERIAL, "amount": amount, "currency": "XAF",
            "purpose": "Achat structure", "beneficiary": "Fournisseur BTP", "milestone": self.stage,
            "due_date": date.today() + timedelta(days=3), "create_mode": "submitted",
        })
        for document_type, evidence_type in (("quote", EvidenceRecord.Type.QUOTE), ("invoice", EvidenceRecord.Type.INVOICE)):
            attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type=document_type, evidence=self.evidence(evidence_type, document_type))
        if amount >= 500000:
            attach_expense_evidence(actor=self.contractor, expense_request=expense, document_type="delivery_note", evidence=self.evidence(EvidenceRecord.Type.DELIVERY_NOTE, "Bon"))
        expense = transition_expense_request(actor=self.contractor, expense_request=expense, target_status="evidence", expected_version=expense.status_version)
        expense = transition_expense_request(actor=self.contractor, expense_request=expense, target_status="review", expected_version=expense.status_version)
        _, expense = submit_expense_technical_opinion(actor=self.engineer, expense_request=expense, decision=opinion, reason="Avis documenté", expected_version=expense.status_version)
        return expense

    def test_risk_rules_make_pivot_review_mandatory(self):
        expense = self.verified_request()
        risk = evaluate_expense_risk(expense)
        self.assertTrue(risk["required"])
        self.assertGreaterEqual(risk["score"], 35)
        self.assertTrue(risk["reasons"])

    def test_owner_authorization_is_blocked_until_matching_pivot_approval(self):
        expense = self.verified_request()
        with self.assertRaises(ValidationError):
            decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        verification, unchanged = submit_expense_pivot_verification(actor=self.reviewer, expense_request=expense, decision="approved", reason="Pièces et quantités cohérentes", expected_version=expense.status_version)
        self.assertEqual(unchanged.status, ExpenseRequest.Status.VERIFIED)
        _, expense = decide_expense_by_owner(actor=self.owner, expense_request=expense, decision="approved", reason="", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.AUTHORIZED)
        self.assertEqual(PaymentTransaction.objects.count(), 0)
        self.assertEqual(verification.reviewed_status_version, expense.status_version - 1)

    def test_pivot_rejection_returns_to_evidence_and_keeps_history(self):
        expense = self.verified_request()
        verification, expense = submit_expense_pivot_verification(actor=self.reviewer, expense_request=expense, decision="rejected", reason="Livraison incohérente", expected_version=expense.status_version)
        self.assertEqual(expense.status, ExpenseRequest.Status.EVIDENCE)
        self.assertEqual(verification.decision, ExpensePivotVerification.Decision.REJECTED)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.pivot_verification_submitted", target_id=str(verification.pk)).exists())

    def test_non_reviewer_and_stale_version_are_rejected(self):
        expense = self.verified_request()
        with self.assertRaises(PermissionDenied):
            submit_expense_pivot_verification(actor=self.engineer, expense_request=expense, decision="approved", reason="Non autorisé", expected_version=expense.status_version)
        with self.assertRaises(ValidationError):
            submit_expense_pivot_verification(actor=self.reviewer, expense_request=expense, decision="approved", reason="Version ancienne", expected_version=expense.status_version - 1)

    def test_incoherent_stage_blocks_pivot_verification(self):
        expense = self.verified_request()
        other_stage = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Finitions", start_date=date.today(), end_date=date.today() + timedelta(days=5), created_by=self.engineer)
        # Injection d’une incohérence simulant une donnée historique importée.
        from apps.finance.models import ExpenseRequestAttachment
        ExpenseRequestAttachment.objects.create(organization=self.organization, request=expense, evidence=self.evidence(EvidenceRecord.Type.PHOTO, "Mauvais jalon", stage=other_stage), document_type="progress_evidence", added_by=self.contractor)
        with self.assertRaises(ValidationError):
            submit_expense_pivot_verification(actor=self.reviewer, expense_request=expense, decision="approved", reason="À contrôler", expected_version=expense.status_version)

    def test_exceptional_intervention_requires_explicit_confirmation_and_is_audited(self):
        expense = self.verified_request()
        with self.assertRaises(ValidationError):
            submit_expense_pivot_verification(actor=self.superuser, expense_request=expense, decision="approved", reason="Intervention nécessaire", expected_version=expense.status_version, is_exceptional=True, confirmation="oui")
        verification, _ = submit_expense_pivot_verification(actor=self.superuser, expense_request=expense, decision="approved", reason="Intervention nécessaire", expected_version=expense.status_version, is_exceptional=True, confirmation=EXCEPTIONAL_PIVOT_CONFIRMATION)
        self.assertTrue(verification.is_exceptional)
        self.assertTrue(AuditEvent.objects.filter(action="expense_request.pivot_exceptional_intervention", target_id=str(verification.pk), metadata__exceptional_confirmation=True).exists())
