import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.collaboration.models import EvidenceRecord, ProjectDocument, ProjectImage
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project


class EvidenceRegistryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.organization = Organization.objects.create(name="Evidence Org", slug="evidence-org")
        self.other_organization = Organization.objects.create(name="Other Evidence", slug="other-evidence")
        self.author = User.objects.create_user(username="evidence-author", organization=self.organization, role=User.Role.ENGINEER)
        self.other_author = User.objects.create_user(username="other-evidence-author", organization=self.other_organization, role=User.Role.ENGINEER)
        self.project = Project.objects.create(organization=self.organization, engineer=self.author, name="Evidence project", location="Douala", project_date="2027-01-01")
        self.other_project = Project.objects.create(organization=self.other_organization, engineer=self.other_author, name="Other project", location="Yaoundé", project_date="2027-01-01")

    def test_existing_document_and_photo_are_registered_without_moving_files(self):
        document = ProjectDocument.objects.create(
            organization=self.organization, project=self.project, uploaded_by=self.author,
            title="Facture ciment", file=SimpleUploadedFile("facture.pdf", b"pdf"),
        )
        image = ProjectImage.objects.create(
            organization=self.organization, project=self.project, uploaded_by=self.author,
            caption="Fondations", image=SimpleUploadedFile("photo.jpg", b"image"),
        )
        document_evidence = EvidenceRecord.objects.get(document=document)
        image_evidence = EvidenceRecord.objects.get(image=image)
        self.assertEqual(document_evidence.evidence_type, EvidenceRecord.Type.INVOICE)
        self.assertEqual(image_evidence.evidence_type, EvidenceRecord.Type.PHOTO)
        self.assertEqual(document_evidence.document.file.name, document.file.name)
        self.assertEqual(image_evidence.image.image.name, image.image.name)

    def test_all_required_evidence_types_are_available(self):
        values = set(EvidenceRecord.Type.values)
        self.assertTrue({"photo", "video", "invoice", "quote", "delivery_note", "minutes", "inspection"}.issubset(values))

    def test_version_stage_and_request_are_traceable(self):
        stage = ProjectStage.objects.create(
            organization=self.organization, project=self.project, title="Fondations",
            start_date="2027-01-01", end_date="2027-01-10", created_by=self.author,
        )
        key = uuid.uuid4()
        first = EvidenceRecord.objects.create(
            evidence_key=key, organization=self.organization, project=self.project,
            author=self.author, stage=stage, evidence_type="inspection", title="Inspection v1",
            request_type="withdrawal", request_id="REQ-1",
        )
        second = EvidenceRecord.objects.create(
            evidence_key=key, version=2, previous_version=first,
            correction_reason="Mise à jour de la pièce",
            organization=self.organization, project=self.project, author=self.author,
            stage=stage, evidence_type="inspection", title="Inspection v2",
            request_type="withdrawal", request_id="REQ-1",
        )
        self.assertEqual(second.previous_version, first)
        self.assertEqual(second.stage, stage)
        self.assertEqual(second.request_id, "REQ-1")

    def test_cross_organization_associations_are_rejected(self):
        foreign_document = ProjectDocument.objects.create(
            organization=self.other_organization, project=self.other_project,
            uploaded_by=self.other_author, title="Devis externe",
            file=SimpleUploadedFile("devis.pdf", b"pdf"),
        )
        with self.assertRaises(ValidationError):
            EvidenceRecord.objects.create(
                organization=self.organization, project=self.project, author=self.author,
                document=foreign_document, evidence_type="quote", title="Association interdite",
            )
