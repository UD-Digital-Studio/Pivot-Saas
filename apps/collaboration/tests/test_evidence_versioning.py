from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord
from apps.collaboration.services import correct_evidence, review_evidence
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


class EvidenceVersioningTests(TestCase):
    def setUp(self):
        self.storage = self.settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.memory.InMemoryStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
        self.storage.enable()
        self.addCleanup(self.storage.disable)
        User = get_user_model()
        self.organization = Organization.objects.create(name="Versions", slug="versions")
        self.engineer = User.objects.create_user(username="version-engineer", organization=self.organization, role=User.Role.ENGINEER)
        self.admin = User.objects.create_superuser(username="version-admin", email="admin@example.test", password="pass")
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Projet versions", location="Douala", project_date="2027-01-01")

    def evidence(self, status=EvidenceRecord.Status.VERIFIED):
        return EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, author=self.engineer,
            evidence_type=EvidenceRecord.Type.DOCUMENT, title="PV initial", status=status,
            uploaded_file=SimpleUploadedFile("pv.pdf", b"%PDF-1.7"),
        )

    def correction_data(self, reason="Erreur de date"):
        return {"title": "PV corrigé", "description": "Nouvelle pièce", "stage": None,
                "uploaded_file": SimpleUploadedFile("pv-v2.pdf", b"%PDF-1.7"),
                "correction_reason": reason, "location_consent": False,
                "location_status": EvidenceRecord.LocationStatus.NOT_REQUESTED}

    def test_validated_evidence_cannot_be_overwritten_or_deleted(self):
        evidence = self.evidence()
        evidence.title = "Titre réécrit"
        with self.assertRaises(ValidationError):
            evidence.save()
        evidence.refresh_from_db()
        with self.assertRaises(ValidationError):
            evidence.delete()
        self.assertTrue(EvidenceRecord.objects.filter(pk=evidence.pk).exists())

    def test_correction_creates_linked_version_and_preserves_original(self):
        original = self.evidence()
        corrected = correct_evidence(actor=self.engineer, original=original, data=self.correction_data())
        original.refresh_from_db()
        self.assertEqual(original.title, "PV initial")
        self.assertEqual(corrected.version, 2)
        self.assertEqual(corrected.previous_version, original)
        self.assertEqual(corrected.evidence_key, original.evidence_key)
        self.assertEqual(corrected.correction_reason, "Erreur de date")
        self.assertEqual(corrected.status, EvidenceRecord.Status.SUBMITTED)
        self.assertTrue(AuditEvent.objects.filter(action="evidence.corrected", target_id=str(corrected.pk)).exists())

    def test_administrative_correction_is_explicit_and_audited(self):
        original = self.evidence(status=EvidenceRecord.Status.APPROVED)
        corrected = correct_evidence(actor=self.admin, original=original, data=self.correction_data("Correction exceptionnelle"))
        self.assertTrue(corrected.is_administrative_correction)
        event = AuditEvent.objects.get(action="evidence.corrected", target_id=str(corrected.pk))
        self.assertTrue(event.metadata["administrative"])

    def test_only_latest_version_can_be_corrected(self):
        original = self.evidence()
        correct_evidence(actor=self.engineer, original=original, data=self.correction_data())
        with self.assertRaises(ValidationError):
            correct_evidence(actor=self.engineer, original=original, data=self.correction_data("Autre"))

    def test_verification_then_approval_preserves_exact_version(self):
        evidence = self.evidence(status=EvidenceRecord.Status.SUBMITTED)
        review_evidence(actor=self.engineer, evidence=evidence, decision=EvidenceRecord.Status.VERIFIED)
        evidence.refresh_from_db()
        self.assertEqual(evidence.status, EvidenceRecord.Status.VERIFIED)
        review_evidence(actor=self.admin, evidence=evidence, decision=EvidenceRecord.Status.APPROVED)
        evidence.refresh_from_db()
        self.assertEqual(evidence.status, EvidenceRecord.Status.APPROVED)
        self.assertTrue(AuditEvent.objects.filter(action="evidence.approved", target_id=str(evidence.pk), metadata__version=1).exists())
