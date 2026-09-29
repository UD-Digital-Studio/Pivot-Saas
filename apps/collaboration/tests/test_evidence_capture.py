from io import BytesIO
import uuid

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.audit.models import AuditEvent
from apps.audit.models import PlatformConfiguration
from apps.collaboration.models import EvidenceRecord
from apps.collaboration.services import can_access_evidence, can_view_evidence_location
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import Project, ProjectMembership


class EvidenceCaptureTests(TestCase):
    def setUp(self):
        self.settings_override = self.settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.memory.InMemoryStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        User = get_user_model()
        self.organization = Organization.objects.create(name="Terrain", slug="terrain")
        self.engineer = User.objects.create_user(username="engineer-evidence", organization=self.organization, role=User.Role.ENGINEER)
        self.manager = User.objects.create_user(username="manager-evidence", organization=self.organization, role=User.Role.SITE_MANAGER)
        self.client_user = User.objects.create_user(username="client-evidence", organization=self.organization, role=User.Role.CLIENT)
        self.project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Chantier", location="Douala", project_date="2027-01-01")
        ProjectMembership.objects.create(organization=self.organization, project=self.project, user=self.manager, project_role=ProjectMembership.Role.SITE_MANAGER)
        self.stage = ProjectStage.objects.create(organization=self.organization, project=self.project, title="Fondations", start_date="2027-01-01", end_date="2027-01-10", created_by=self.engineer)
        self.url = reverse("collaboration:evidence-create", args=(self.project.pk,))

    def test_site_manager_can_upload_real_photo_with_stage_and_audit(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.url, {"evidence_type": "photo", "title": "Fondations", "description": "Vue terrain", "stage": self.stage.pk, "uploaded_file": SimpleUploadedFile("terrain.jpg", b"\xff\xd8\xff\xe0photo", content_type="image/jpeg")}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        evidence = EvidenceRecord.objects.get(title="Fondations")
        self.assertEqual(evidence.author, self.manager)
        self.assertEqual(evidence.stage, self.stage)
        self.assertTrue(AuditEvent.objects.filter(action="evidence.created", target_id=str(evidence.pk)).exists())

    def test_video_has_authenticated_inline_preview(self):
        self.client.force_login(self.manager)
        self.client.post(self.url, {"evidence_type": "video", "title": "Visite", "uploaded_file": SimpleUploadedFile("visite.mp4", b"\x00\x00\x00\x18ftypmp42video", content_type="video/mp4")})
        evidence = EvidenceRecord.objects.get(title="Visite")
        preview = self.client.get(reverse("collaboration:evidence-file", args=(self.project.pk, evidence.pk)))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview["Content-Type"], "video/mp4")
        self.assertEqual(preview["X-Content-Type-Options"], "nosniff")

    def test_extension_spoofing_is_rejected(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.url, {"evidence_type": "photo", "title": "Fausse photo", "uploaded_file": SimpleUploadedFile("fake.jpg", b"not-an-image", content_type="image/jpeg")}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EvidenceRecord.objects.filter(title="Fausse photo").exists())

    def test_unassigned_client_cannot_capture_or_read_evidence(self):
        self.client.force_login(self.manager)
        self.client.post(self.url, {"evidence_type": "document", "title": "PV", "uploaded_file": SimpleUploadedFile("pv.pdf", b"%PDF-1.7", content_type="application/pdf")})
        evidence = EvidenceRecord.objects.get(title="PV")
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.post(self.url, {}).status_code, 404)
        self.assertEqual(self.client.get(reverse("collaboration:evidence-file", args=(self.project.pk, evidence.pk))).status_code, 404)

    def test_consented_location_and_server_context_are_recorded(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.url, {
            "evidence_type": "document", "title": "Inspection géolocalisée",
            "uploaded_file": SimpleUploadedFile("inspection.pdf", b"%PDF-1.7", content_type="application/pdf"),
            "location_consent": "on", "location_status": "granted",
            "latitude": "4.051100", "longitude": "9.767900", "location_accuracy_m": "12",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        evidence = EvidenceRecord.objects.get(title="Inspection géolocalisée")
        self.assertEqual(evidence.author, self.manager)
        self.assertIsNotNone(evidence.captured_at)
        self.assertTrue(evidence.location_consent)
        self.assertEqual(evidence.location_status, EvidenceRecord.LocationStatus.GRANTED)
        self.assertEqual(evidence.location_accuracy_m, 12)

    def test_refused_location_does_not_block_upload_or_store_coordinates(self):
        self.client.force_login(self.manager)
        response = self.client.post(self.url, {
            "evidence_type": "document", "title": "Sans position",
            "uploaded_file": SimpleUploadedFile("preuve.pdf", b"%PDF-1.7", content_type="application/pdf"),
            "location_consent": "on", "location_status": "denied",
            "latitude": "4.000000", "longitude": "9.000000",
        })
        self.assertEqual(response.status_code, 302)
        evidence = EvidenceRecord.objects.get(title="Sans position")
        self.assertEqual(evidence.location_status, EvidenceRecord.LocationStatus.DENIED)
        self.assertIsNone(evidence.latitude)
        self.assertIsNone(evidence.longitude)

    def test_location_access_is_project_role_scoped(self):
        self.assertTrue(can_view_evidence_location(actor=self.engineer, project=self.project))
        self.assertFalse(can_view_evidence_location(actor=self.manager, project=self.project))
        self.assertFalse(can_view_evidence_location(actor=self.client_user, project=self.project))

    def test_photo_preview_is_compressed_without_changing_original(self):
        source = BytesIO()
        Image.new("RGB", (1800, 1200), color=(20, 80, 160)).save(source, format="JPEG", quality=95)
        original_bytes = source.getvalue()
        self.client.force_login(self.manager)
        self.client.post(self.url, {"evidence_type": "photo", "title": "Grande photo", "uploaded_file": SimpleUploadedFile("grande.jpg", original_bytes, content_type="image/jpeg")})
        evidence = EvidenceRecord.objects.get(title="Grande photo")
        self.assertTrue(evidence.preview_file)
        with evidence.uploaded_file.open("rb") as original:
            self.assertEqual(original.read(), original_bytes)
        with evidence.preview_file.open("rb") as preview:
            preview_bytes = preview.read()
        self.assertNotEqual(preview_bytes, original_bytes)
        self.assertLess(len(preview_bytes), len(original_bytes))

    def test_retry_with_same_submission_id_does_not_duplicate(self):
        self.client.force_login(self.manager)
        submission_id = uuid.uuid4()
        payload = {"evidence_type": "document", "title": "Bon unique", "submission_id": str(submission_id), "uploaded_file": SimpleUploadedFile("bon.pdf", b"%PDF-1.7")}
        first = self.client.post(self.url, payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second_payload = {"evidence_type": "document", "title": "Bon unique", "submission_id": str(submission_id), "uploaded_file": SimpleUploadedFile("bon.pdf", b"%PDF-1.7")}
        second = self.client.post(self.url, second_payload, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(first.status_code, 200)
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(EvidenceRecord.objects.filter(submission_id=submission_id).count(), 1)

    def test_capture_interface_exposes_accessible_loading_and_retry_states(self):
        self.client.force_login(self.manager)
        response = self.client.get(f"{self.project.get_absolute_url()}?tab=evidence")
        self.assertContains(response, 'aria-busy="false"')
        self.assertContains(response, 'role="progressbar"')
        self.assertContains(response, "Réessayer")
        self.assertContains(response, "h-[100dvh]")

    def test_preview_download_and_export_share_the_approval_policy(self):
        evidence = EvidenceRecord.objects.create(
            organization=self.organization, project=self.project, author=self.manager,
            evidence_type=EvidenceRecord.Type.DOCUMENT, title="Confidentiel",
            uploaded_file=SimpleUploadedFile("confidentiel.pdf", b"%PDF-1.7"),
        )
        self.client.force_login(self.manager)
        preview = self.client.get(reverse("collaboration:evidence-file", args=(self.project.pk, evidence.pk)))
        download_url = reverse("collaboration:evidence-download", args=(self.project.pk, evidence.pk))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(self.client.get(download_url).status_code, 403)
        self.assertFalse(can_access_evidence(actor=self.manager, evidence=evidence, action="export"))
        evidence.status = EvidenceRecord.Status.APPROVED
        evidence.save(update_fields=("status",))
        self.assertEqual(self.client.get(download_url).status_code, 200)
        self.assertTrue(can_access_evidence(actor=self.manager, evidence=evidence, action="export"))
        self.assertTrue(AuditEvent.objects.filter(action="evidence.downloaded", target_id=str(evidence.pk), metadata__version=1).exists())

    def test_privacy_configuration_controls_operational_location_access(self):
        configuration = PlatformConfiguration.load()
        self.assertFalse(can_view_evidence_location(actor=self.manager, project=self.project))
        configuration.evidence_location_restricted = False
        configuration.save(update_fields=("evidence_location_restricted",))
        self.assertTrue(can_view_evidence_location(actor=self.manager, project=self.project))

    def test_direct_file_url_cannot_cross_project_scope(self):
        other_project = Project.objects.create(organization=self.organization, engineer=self.engineer, name="Autre chantier", location="Bafoussam", project_date="2027-01-02")
        evidence = EvidenceRecord.objects.create(organization=self.organization, project=other_project, author=self.engineer, evidence_type=EvidenceRecord.Type.DOCUMENT, title="Autre", status=EvidenceRecord.Status.APPROVED, uploaded_file=SimpleUploadedFile("autre.pdf", b"%PDF-1.7"))
        self.client.force_login(self.manager)
        response = self.client.get(reverse("collaboration:evidence-download", args=(other_project.pk, evidence.pk)))
        self.assertEqual(response.status_code, 404)
