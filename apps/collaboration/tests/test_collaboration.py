from datetime import date
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.audit.models import AuditEvent
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage
from apps.organizations.models import Organization
from apps.projects.models import Project, ProjectMembership


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class CollaborationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Collab Corp", slug="collab-corp")
        self.other = Organization.objects.create(name="Other Collab", slug="other-collab")
        self.engineer = get_user_model().objects.create_user(
            username="collab-engineer", organization=self.organization, role="engineer"
        )
        self.client_user = get_user_model().objects.create_user(
            username="collab-client", organization=self.organization, role="client"
        )
        self.manager = get_user_model().objects.create_user(
            username="collab-manager", organization=self.organization, role="site_manager"
        )
        self.other_engineer = get_user_model().objects.create_user(
            username="other-collab-engineer", organization=self.other, role="engineer"
        )
        self.project = Project.objects.create(
            organization=self.organization,
            engineer=self.engineer,
            name="Projet collaboration",
            location="Douala",
            project_date=date.today(),
        )
        for user in (self.client_user, self.manager):
            ProjectMembership.objects.create(
                organization=self.organization,
                project=self.project,
                user=user,
                project_role=(
                    ProjectMembership.Role.OWNER
                    if user.role == user.Role.CLIENT
                    else ProjectMembership.Role.SITE_MANAGER
                ),
            )

    def pdf(self):
        return SimpleUploadedFile("plan.pdf", b"%PDF-1.4 test", content_type="application/pdf")

    def image(self):
        buffer = BytesIO()
        Image.new("RGB", (3, 3), "red").save(buffer, "PNG")
        return SimpleUploadedFile("chantier.png", buffer.getvalue(), content_type="image/png")

    def test_assigned_member_uploads_pending_pdf(self):
        self.client.force_login(self.client_user)
        response = self.client.post(
            reverse("collaboration:document-upload", kwargs={"project_pk": self.project.pk}),
            {"title": "Plan", "file": self.pdf()},
        )
        self.assertEqual(response.status_code, 302)
        document = ProjectDocument.objects.get()
        self.assertEqual(document.status, "pending")
        self.assertEqual(document.organization, self.organization)

    def test_invalid_document_type_is_rejected(self):
        self.client.force_login(self.client_user)
        fake = SimpleUploadedFile("virus.exe", b"bad", content_type="application/octet-stream")
        self.client.post(
            reverse("collaboration:document-upload", kwargs={"project_pk": self.project.pk}),
            {"title": "Bad", "file": fake},
        )
        self.assertFalse(ProjectDocument.objects.exists())

    def test_pending_document_is_private_then_approved_is_visible(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Privé",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        self.client.force_login(self.manager)
        denied = self.client.get(
            reverse(
                "collaboration:document-download",
                kwargs={"project_pk": self.project.pk, "pk": document.pk},
            )
        )
        document.status = "approved"
        document.save(update_fields=("status",))
        allowed = self.client.get(
            reverse(
                "collaboration:document-download",
                kwargs={"project_pk": self.project.pk, "pk": document.pk},
            )
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_pending_document_cannot_be_downloaded_by_uploader_or_engineer(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="En validation",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        url = reverse(
            "collaboration:document-download",
            kwargs={"project_pk": self.project.pk, "pk": document.pk},
        )
        for user in (self.client_user, self.engineer):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_pending_document_preview_is_limited_to_engineer_then_verified_is_visible(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Plan aperçu",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        url = reverse(
            "collaboration:document-preview",
            kwargs={"project_pk": self.project.pk, "pk": document.pk},
        )
        self.client.force_login(self.client_user)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.engineer)
        self.assertEqual(self.client.get(url).status_code, 200)

        document.status = ProjectDocument.Status.VERIFIED
        document.save(update_fields=("status",))
        self.client.force_login(self.client_user)
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])

    def test_document_search_sort_and_counts_are_scoped_to_project(self):
        ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Plan structure",
            file=self.pdf(),
            uploaded_by=self.client_user,
            status=ProjectDocument.Status.APPROVED,
        )
        ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Devis plomberie",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}),
            {"tab": "documents", "document_q": "structure", "document_status": "approved"},
        )

        self.assertContains(response, "Plan structure")
        self.assertNotContains(response, "Devis plomberie")
        self.assertEqual(response.context["collaboration_counts"]["documents"], 2)
        self.assertContains(response, "Aperçu")

    def test_pending_document_is_listed_for_members_but_preview_is_engineer_only(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Document confidentiel en attente",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        detail_url = reverse("projects:detail", kwargs={"pk": self.project.pk})

        for user in (self.client_user, self.manager):
            self.client.force_login(user)
            response = self.client.get(detail_url, {"tab": "documents"})
            self.assertContains(response, document.title)
            self.assertContains(response, "Verrouillé")
            self.assertNotContains(
                response,
                reverse(
                    "collaboration:document-preview",
                    kwargs={"project_pk": self.project.pk, "pk": document.pk},
                ),
            )
            self.assertEqual(response.context["collaboration_counts"]["documents"], 1)

        self.client.force_login(self.engineer)
        response = self.client.get(detail_url, {"tab": "documents"})
        self.assertContains(response, document.title)
        self.assertContains(response, "Vérifier")
        self.assertEqual(response.context["collaboration_counts"]["documents"], 1)

    def test_engineer_verifies_document_without_unlocking_download(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Plan à vérifier",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        self.client.force_login(self.engineer)

        response = self.client.post(
            reverse(
                "collaboration:document-review",
                kwargs={"project_pk": self.project.pk, "pk": document.pk},
            ),
            {"decision": ProjectDocument.Status.VERIFIED, "reason": "Document lisible."},
        )

        self.assertEqual(response.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, ProjectDocument.Status.VERIFIED)
        download_url = reverse(
            "collaboration:document-download",
            kwargs={"project_pk": self.project.pk, "pk": document.pk},
        )
        self.assertEqual(self.client.get(download_url).status_code, 403)

    def test_engineer_reviews_document_with_audit(self):
        document = ProjectDocument.objects.create(
            organization=self.organization,
            project=self.project,
            title="Plan",
            file=self.pdf(),
            uploaded_by=self.client_user,
        )
        self.client.force_login(self.engineer)
        response = self.client.post(
            reverse(
                "collaboration:document-review",
                kwargs={"project_pk": self.project.pk, "pk": document.pk},
            ),
            {"decision": "rejected", "reason": "Version illisible"},
        )
        self.assertEqual(response.status_code, 302)
        document.refresh_from_db()
        self.assertEqual(document.status, "rejected")
        self.assertEqual(document.reviewed_by, self.engineer)
        self.assertIsNotNone(document.reviewed_at)
        self.assertTrue(AuditEvent.objects.filter(action="document.reviewed").exists())

    def test_gallery_cover_is_unique_and_foreign_access_is_refused(self):
        first = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            image=self.image(),
            uploaded_by=self.client_user,
        )
        second = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            image=self.image(),
            uploaded_by=self.manager,
            is_cover=True,
        )
        self.client.force_login(self.engineer)
        self.client.post(
            reverse(
                "collaboration:image-cover", kwargs={"project_pk": self.project.pk, "pk": first.pk}
            )
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_cover)
        self.assertFalse(second.is_cover)
        self.client.force_login(self.other_engineer)
        denied = self.client.get(
            reverse(
                "collaboration:image-download",
                kwargs={"project_pk": self.project.pk, "pk": first.pk},
            )
        )
        self.assertEqual(denied.status_code, 404)

    def test_other_member_cannot_delete_image(self):
        image = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            image=self.image(),
            uploaded_by=self.client_user,
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse(
                "collaboration:image-delete", kwargs={"project_pk": self.project.pk, "pk": image.pk}
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_photo_delete_uses_only_the_pivot_confirmation_modal(self):
        image = ProjectImage.objects.create(
            organization=self.organization,
            project=self.project,
            image=self.image(),
            uploaded_by=self.engineer,
            caption="Photo à supprimer",
        )
        self.client.force_login(self.engineer)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}), {"tab": "photos"}
        )

        self.assertContains(response, 'id="modal-delete-confirm"')
        self.assertContains(
            response,
            reverse(
                "collaboration:image-delete",
                kwargs={"project_pk": self.project.pk, "pk": image.pk},
            ),
        )
        self.assertNotContains(response, "return confirm(")

    def test_comments_are_ordered_escaped_and_csrf_protected(self):
        ProjectComment.objects.create(
            organization=self.organization,
            project=self.project,
            author=self.client_user,
            content="Premier",
        )
        ProjectComment.objects.create(
            organization=self.organization,
            project=self.project,
            author=self.manager,
            content="<script>alert(1)</script>",
        )
        self.client.force_login(self.client_user)
        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}), {"tab": "comments"}
        )
        comments = list(response.context["project_comments"])
        self.assertEqual(comments[0].author, self.manager)
        self.assertNotContains(response, "<script>alert(1)</script>", html=False)
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;", html=False)
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.client_user)
        denied = csrf_client.post(
            reverse("collaboration:comment-create", kwargs={"project_pk": self.project.pk}),
            {"content": "Sans jeton"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_comments_are_paginated_and_visible_count_excludes_deleted(self):
        for index in range(12):
            ProjectComment.objects.create(
                organization=self.organization,
                project=self.project,
                author=self.client_user,
                content=f"Message {index}",
                is_deleted=index == 0,
            )
        self.client.force_login(self.client_user)

        response = self.client.get(
            reverse("projects:detail", kwargs={"pk": self.project.pk}),
            {"tab": "comments"},
        )

        self.assertEqual(len(response.context["comment_page"]), 10)
        self.assertEqual(response.context["comment_page"].paginator.count, 12)
        self.assertEqual(response.context["collaboration_counts"]["comments"], 11)
        self.assertContains(response, "Pagination des commentaires")

    def test_author_edits_and_deletes_with_content_erasure(self):
        comment = ProjectComment.objects.create(
            organization=self.organization,
            project=self.project,
            author=self.client_user,
            content="Original",
        )
        self.client.force_login(self.client_user)
        self.client.post(
            reverse(
                "collaboration:comment-update",
                kwargs={"project_pk": self.project.pk, "pk": comment.pk},
            ),
            {"content": "Corrigé"},
        )
        self.client.post(
            reverse(
                "collaboration:comment-delete",
                kwargs={"project_pk": self.project.pk, "pk": comment.pk},
            )
        )
        comment.refresh_from_db()
        self.assertTrue(comment.is_deleted)
        self.assertEqual(comment.content, "")
        self.assertIsNotNone(comment.deleted_at)

    def test_only_author_can_edit_or_delete_comment(self):
        comment = ProjectComment.objects.create(
            organization=self.organization,
            project=self.project,
            author=self.client_user,
            content="Texte",
        )
        url = reverse(
            "collaboration:comment-update", kwargs={"project_pk": self.project.pk, "pk": comment.pk}
        )
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(url, {"content": "Interdit"}).status_code, 403)
        self.client.force_login(self.engineer)
        self.assertEqual(self.client.post(url, {"content": "Interdit"}).status_code, 403)
        delete_url = reverse(
            "collaboration:comment-delete",
            kwargs={"project_pk": self.project.pk, "pk": comment.pk},
        )
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        comment.refresh_from_db()
        self.assertFalse(comment.is_deleted)
        self.assertEqual(comment.content, "Texte")
