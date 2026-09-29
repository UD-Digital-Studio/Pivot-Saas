from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone

from apps.projects.selectors import projects_for_user
from apps.projects.services import can_manage_project

from .forms import CommentForm, DocumentForm, DocumentReviewForm, EvidenceCaptureForm, EvidenceCorrectionForm, EvidenceDecisionForm, ImageForm
from .models import EvidenceRecord, ProjectComment, ProjectDocument, ProjectImage
from .services import audit_evidence_access, can_access_evidence, can_preview_document, can_read_document, correct_evidence, create_evidence, review_document, review_evidence, set_cover


def project_redirect(project, tab):
    return redirect(f"{project.get_absolute_url()}?tab={tab}")


def accessible_project(request, project_pk):
    return get_object_or_404(projects_for_user(request.user), pk=project_pk)


@login_required
def evidence_create(request, project_pk):
    project = accessible_project(request, project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = EvidenceCaptureForm(request.POST, request.FILES, project=project)
    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if form.is_valid():
        evidence = create_evidence(actor=request.user, project=project, data=form.cleaned_data)
        if is_ajax:
            duplicate = getattr(evidence, "was_duplicate", False)
            return JsonResponse({"ok": True, "duplicate": duplicate, "message": "Ce dépôt avait déjà été enregistré." if duplicate else "Preuve déposée avec succès.", "id": str(evidence.pk)})
        messages.success(request, "La preuve a été déposée.")
        return project_redirect(project, "evidence")
    if is_ajax:
        return JsonResponse({"ok": False, "errors": form.errors.get_json_data()}, status=400)
    messages.error(request, "Le fichier est invalide. Vérifiez son format et sa taille.")
    return project_redirect(project, "evidence")


@login_required
def evidence_file(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    evidence = get_object_or_404(EvidenceRecord, pk=pk, project=project, organization=project.organization)
    if not can_access_evidence(actor=request.user, evidence=evidence, action="preview"):
        raise PermissionDenied
    if not evidence.uploaded_file:
        raise PermissionDenied
    suffix = evidence.uploaded_file.name.rsplit(".", 1)[-1].lower()
    content_types = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf"}
    response = FileResponse(evidence.uploaded_file.open("rb"), as_attachment=False, filename=evidence.uploaded_file.name.rsplit("/", 1)[-1], content_type=content_types.get(suffix, "application/octet-stream"))
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; media-src 'self'; img-src 'self'"
    return response


@login_required
def evidence_preview(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    evidence = get_object_or_404(EvidenceRecord, pk=pk, project=project, organization=project.organization, evidence_type=EvidenceRecord.Type.PHOTO)
    if not can_access_evidence(actor=request.user, evidence=evidence, action="preview"):
        raise PermissionDenied
    selected_file = evidence.preview_file or evidence.uploaded_file
    if not selected_file:
        raise PermissionDenied
    response = FileResponse(selected_file.open("rb"), as_attachment=False, filename=f"apercu-v{evidence.version}.jpg", content_type="image/jpeg")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
def evidence_download(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    evidence = get_object_or_404(EvidenceRecord, pk=pk, project=project, organization=project.organization)
    if not evidence.uploaded_file or not can_access_evidence(actor=request.user, evidence=evidence, action="download"):
        raise PermissionDenied
    audit_evidence_access(actor=request.user, evidence=evidence, action="downloaded")
    response = FileResponse(evidence.uploaded_file.open("rb"), as_attachment=True, filename=evidence.uploaded_file.name.rsplit("/", 1)[-1])
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def evidence_correct(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    original = get_object_or_404(EvidenceRecord, pk=pk, project=project, organization=project.organization)
    if request.method != "POST":
        raise PermissionDenied
    form = EvidenceCorrectionForm(request.POST, request.FILES, project=project, original=original)
    if form.is_valid():
        try:
            evidence = correct_evidence(actor=request.user, original=original, data=form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f"Correction enregistrée comme version {evidence.version}.")
    else:
        messages.error(request, "La correction est invalide. Vérifiez le fichier et le motif.")
    return project_redirect(project, "evidence")


@login_required
def evidence_review(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    evidence = get_object_or_404(EvidenceRecord, pk=pk, project=project, organization=project.organization)
    if request.method != "POST":
        raise PermissionDenied
    form = EvidenceDecisionForm(request.POST)
    if form.is_valid():
        try:
            review_evidence(actor=request.user, evidence=evidence, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "La décision sur la preuve a été enregistrée.")
    else:
        messages.error(request, "Décision invalide.")
    return project_redirect(project, "evidence")


@login_required
def document_upload(request, project_pk):
    project = accessible_project(request, project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = DocumentForm(request.POST, request.FILES)
    if form.is_valid():
        document = form.save(commit=False)
        document.organization = project.organization
        document.project = project
        document.uploaded_by = request.user
        document.save()
        messages.success(request, "Le document a été déposé et attend une validation.")
    else:
        messages.error(request, "PDF invalide ou trop volumineux.")
    return project_redirect(project, "documents")


@login_required
def document_download(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    document = get_object_or_404(
        ProjectDocument, pk=pk, project=project, organization=project.organization
    )
    if not can_read_document(actor=request.user, document=document):
        raise PermissionDenied
    return FileResponse(
        document.file.open("rb"), as_attachment=True, filename=document.file.name.rsplit("/", 1)[-1]
    )


@login_required
def document_preview(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    document = get_object_or_404(
        ProjectDocument, pk=pk, project=project, organization=project.organization
    )
    if not can_preview_document(actor=request.user, document=document):
        raise PermissionDenied
    return FileResponse(
        document.file.open("rb"),
        as_attachment=False,
        filename=document.file.name.rsplit("/", 1)[-1],
        content_type="application/pdf",
    )


@login_required
def document_review(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    document = get_object_or_404(
        ProjectDocument, pk=pk, project=project, organization=project.organization
    )
    if request.method != "POST":
        raise PermissionDenied
    form = DocumentReviewForm(request.POST)
    if form.is_valid():
        review_document(actor=request.user, document=document, **form.cleaned_data)
        messages.success(request, "La décision a été enregistrée.")
    else:
        messages.error(request, "La décision ou son motif est invalide.")
    return project_redirect(project, "documents")


@login_required
def image_upload(request, project_pk):
    project = accessible_project(request, project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = ImageForm(request.POST, request.FILES)
    if form.is_valid():
        image = form.save(commit=False)
        image.organization = project.organization
        image.project = project
        image.uploaded_by = request.user
        image.save()
        messages.success(request, "La photo a été ajoutée.")
    else:
        messages.error(request, "L'image est invalide ou trop volumineuse.")
    return project_redirect(project, "photos")


@login_required
def image_download(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    image = get_object_or_404(
        ProjectImage, pk=pk, project=project, organization=project.organization
    )
    return FileResponse(image.image.open("rb"), filename=image.image.name.rsplit("/", 1)[-1])


@login_required
def image_cover(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    image = get_object_or_404(
        ProjectImage, pk=pk, project=project, organization=project.organization
    )
    if request.method != "POST":
        raise PermissionDenied
    set_cover(actor=request.user, image=image)
    messages.success(request, "La couverture a été mise à jour.")
    return project_redirect(project, "photos")


@login_required
def image_delete(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    image = get_object_or_404(
        ProjectImage, pk=pk, project=project, organization=project.organization
    )
    if request.method != "POST":
        raise PermissionDenied
    if image.uploaded_by_id != request.user.pk and not can_manage_project(
        actor=request.user, project=project
    ):
        raise PermissionDenied
    image.delete()
    messages.success(request, "La photo a été supprimée.")
    return project_redirect(project, "photos")


@login_required
def comment_create(request, project_pk):
    project = accessible_project(request, project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.organization = project.organization
        comment.project = project
        comment.author = request.user
        comment.save()
    return project_redirect(project, "comments")


@login_required
def comment_update(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    comment = get_object_or_404(ProjectComment, pk=pk, project=project, is_deleted=False)
    if request.method != "POST" or comment.author_id != request.user.pk:
        raise PermissionDenied
    form = CommentForm(request.POST, instance=comment)
    if form.is_valid():
        form.save()
    return project_redirect(project, "comments")


@login_required
@transaction.atomic
def comment_delete(request, project_pk, pk):
    project = accessible_project(request, project_pk)
    comment = get_object_or_404(ProjectComment, pk=pk, project=project, is_deleted=False)
    if request.method != "POST" or comment.author_id != request.user.pk:
        raise PermissionDenied
    comment.content = ""
    comment.is_deleted = True
    comment.deleted_by = request.user
    comment.deleted_at = timezone.now()
    comment.save(update_fields=("content", "is_deleted", "deleted_by", "deleted_at", "updated_at"))
    return project_redirect(project, "comments")
