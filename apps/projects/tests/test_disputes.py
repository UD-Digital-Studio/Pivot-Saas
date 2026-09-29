from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import ProjectDocument
from apps.collaboration.services import review_document
from apps.organizations.models import Organization
from apps.projects.disputes import add_dispute_observation, open_dispute, resolve_dispute
from apps.projects.models import Project, ProjectDispute, ProjectDisputeObservation


class ProjectDisputeTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Dispute E22", slug="dispute-e22")
        users = get_user_model()
        self.admin = users.objects.create_superuser(username="pivot-dispute", role=users.Role.ADMIN)
        self.engineer = users.objects.create_user(
            username="dispute-engineer", organization=self.organization, role=users.Role.ENGINEER
        )
        self.project = Project.objects.create(
            organization=self.organization, engineer=self.engineer, name="Projet contesté",
            location="Douala", project_date=date.today(),
        )
        self.document = ProjectDocument.objects.create(
            organization=self.organization, project=self.project, title="Facture litigieuse",
            file=SimpleUploadedFile("facture.pdf", b"%PDF-1.4"), uploaded_by=self.engineer,
        )
        review_document(
            actor=self.engineer, document=self.document,
            decision=ProjectDocument.Status.VERIFIED, reason="Vérification initiale",
        )

    def test_frozen_dispute_accepts_contradiction_and_preserves_evidence(self):
        evidence = self.document.evidence_record
        dispute = open_dispute(
            actor=self.admin, project=self.project,
            target_type=ProjectDispute.TargetType.DOCUMENT, target_id=self.document.pk,
            subject="Montant contesté", reason="Le client conteste la facture.",
            freezes_decision=True, evidence=[evidence],
        )
        add_dispute_observation(
            actor=self.engineer, dispute=dispute,
            position=ProjectDisputeObservation.Position.RESPONDENT,
            body="Le montant correspond au bon de livraison.",
        )
        add_dispute_observation(
            actor=self.admin, dispute=dispute,
            position=ProjectDisputeObservation.Position.CLAIMANT,
            body="Le client maintient sa réserve.",
        )

        with self.assertRaisesMessage(ValidationError, "gelée"):
            review_document(
                actor=self.admin, document=self.document,
                decision=ProjectDocument.Status.APPROVED, reason="Trop tôt",
            )
        with self.assertRaises(ProtectedError):
            evidence.delete()

        resolve_dispute(
            actor=self.admin, dispute=dispute,
            resolution="Facture confirmée après rapprochement contradictoire.",
        )
        review_document(
            actor=self.admin, document=self.document,
            decision=ProjectDocument.Status.APPROVED, reason="Contestation résolue",
        )

        dispute.refresh_from_db()
        self.assertEqual(dispute.status, ProjectDispute.Status.RESOLVED)
        self.assertEqual(dispute.observations.count(), 2)
        self.assertTrue(dispute.evidence_links.filter(evidence=evidence).exists())
        self.assertTrue(AuditEvent.objects.filter(action="project.dispute_resolved").exists())
