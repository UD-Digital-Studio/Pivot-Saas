from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from io import BytesIO
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from apps.audit.models import AuditEvent
from apps.audit.models import PlatformConfiguration
from apps.accounts.models import Notification
from apps.accounts.services import create_notification
from apps.projects.services import can_manage_project
from apps.projects.access import PROJECT_TECHNICAL_ROLES, has_project_role

from .models import EvidenceRecord, ProjectDocument, ProjectImage


CAPTURE_ROLES = {"owner", "contractor", "site_manager", "engineer"}
LOCATION_VIEW_ROLES = CAPTURE_ROLES | {"pivot_reviewer"}
EVIDENCE_VIEW_ROLES = LOCATION_VIEW_ROLES


def can_capture_evidence(*, actor, project):
    return has_project_role(user=actor, project=project, roles=CAPTURE_ROLES)


def can_view_evidence_location(*, actor, project):
    configuration = PlatformConfiguration.load()
    roles = {"owner", "engineer", "pivot_reviewer"} if configuration.evidence_location_restricted else LOCATION_VIEW_ROLES
    return has_project_role(user=actor, project=project, roles=roles)


def can_access_evidence(*, actor, evidence, action="preview"):
    if not has_project_role(user=actor, project=evidence.project, roles=EVIDENCE_VIEW_ROLES):
        return False
    if action == "preview":
        return True
    if action in {"download", "export"}:
        configuration = PlatformConfiguration.load()
        return (
            not configuration.evidence_download_requires_approval
            or evidence.status == EvidenceRecord.Status.APPROVED
        )
    return False


def audit_evidence_access(*, actor, evidence, action):
    AuditEvent.objects.create(
        organization=evidence.organization, actor=actor, action=f"evidence.{action}",
        target_type="evidence_record", target_id=str(evidence.pk),
        metadata={"version": evidence.version, "project_id": str(evidence.project_id)},
    )


def can_correct_evidence(*, actor, project):
    return actor.is_superuser or has_project_role(
        user=actor, project=project, roles=PROJECT_TECHNICAL_ROLES
    )


@transaction.atomic
def create_evidence(*, actor, project, data):
    if not can_capture_evidence(actor=actor, project=project):
        raise PermissionDenied
    submission_id = data.get("submission_id") or uuid.uuid4()
    existing = EvidenceRecord.objects.filter(submission_id=submission_id).first()
    if existing:
        if existing.project_id != project.pk or existing.author_id != actor.pk:
            raise ValidationError("Identifiant de dépôt déjà utilisé.")
        existing.was_duplicate = True
        return existing
    evidence = EvidenceRecord.objects.create(
        organization=project.organization,
        project=project,
        author=actor,
        evidence_type=data["evidence_type"],
        title=data["title"],
        description=data.get("description", ""),
        stage=data.get("stage"),
        uploaded_file=data["uploaded_file"],
        submission_id=submission_id,
        location_consent=data.get("location_consent", False),
        location_status=data.get("location_status", EvidenceRecord.LocationStatus.NOT_REQUESTED),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        location_accuracy_m=data.get("location_accuracy_m"),
        source_metadata={"source": "mobile_capture"},
    )
    AuditEvent.objects.create(
        organization=project.organization,
        actor=actor,
        action="evidence.created",
        target_type="evidence_record",
        target_id=str(evidence.pk),
        metadata={"type": evidence.evidence_type, "stage_id": str(evidence.stage_id or ""), "location_status": evidence.location_status},
    )
    if evidence.evidence_type == EvidenceRecord.Type.PHOTO:
        _generate_evidence_preview(evidence)
    evidence.was_duplicate = False
    return evidence


def _generate_evidence_preview(evidence):
    """Create a separate lightweight JPEG; the uploaded original is never rewritten."""
    try:
        evidence.uploaded_file.open("rb")
        image = ImageOps.exif_transpose(Image.open(evidence.uploaded_file))
        image.thumbnail((1280, 1280))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=72, optimize=True)
        evidence.preview_file.save(f"preview-v{evidence.version}.jpg", ContentFile(output.getvalue()), save=False)
        evidence.save(update_fields=("preview_file",))
    except (OSError, UnidentifiedImageError, ValueError):
        return
    finally:
        try:
            evidence.uploaded_file.close()
        except Exception:
            pass


@transaction.atomic
def correct_evidence(*, actor, original, data):
    if not can_correct_evidence(actor=actor, project=original.project):
        raise PermissionDenied
    latest = (
        EvidenceRecord.objects.select_for_update()
        .filter(evidence_key=original.evidence_key)
        .order_by("-version")
        .first()
    )
    if latest.pk != original.pk:
        raise ValidationError("Une version plus récente existe déjà.")
    if original.status not in {EvidenceRecord.Status.VERIFIED, EvidenceRecord.Status.APPROVED}:
        raise ValidationError("Seule une preuve validée peut être corrigée par versionnement.")
    evidence = EvidenceRecord.objects.create(
        evidence_key=original.evidence_key,
        version=original.version + 1,
        previous_version=original,
        correction_reason=data["correction_reason"].strip(),
        is_administrative_correction=actor.is_superuser,
        organization=original.organization,
        project=original.project,
        author=actor,
        evidence_type=original.evidence_type,
        title=data["title"],
        description=data.get("description", ""),
        stage=data.get("stage"),
        uploaded_file=data["uploaded_file"],
        location_consent=data.get("location_consent", False),
        location_status=data.get("location_status", EvidenceRecord.LocationStatus.NOT_REQUESTED),
        latitude=data.get("latitude"), longitude=data.get("longitude"),
        location_accuracy_m=data.get("location_accuracy_m"),
        source_metadata={"source": "versioned_correction"},
    )
    AuditEvent.objects.create(
        organization=original.organization, actor=actor, action="evidence.corrected",
        target_type="evidence_record", target_id=str(evidence.pk),
        metadata={"original_id": str(original.pk), "version": evidence.version, "reason": evidence.correction_reason, "administrative": actor.is_superuser},
    )
    if evidence.evidence_type == EvidenceRecord.Type.PHOTO:
        _generate_evidence_preview(evidence)
    return evidence


@transaction.atomic
def review_evidence(*, actor, evidence, decision, reason=""):
    evidence = EvidenceRecord.objects.select_for_update().get(pk=evidence.pk)
    if actor.is_superuser:
        allowed = {EvidenceRecord.Status.APPROVED, EvidenceRecord.Status.REJECTED}
        if evidence.status != EvidenceRecord.Status.VERIFIED:
            raise ValidationError("La preuve doit d’abord être vérifiée.")
    else:
        if not has_project_role(user=actor, project=evidence.project, roles=PROJECT_TECHNICAL_ROLES):
            raise PermissionDenied
        allowed = {EvidenceRecord.Status.VERIFIED, EvidenceRecord.Status.REJECTED}
        if evidence.status != EvidenceRecord.Status.SUBMITTED:
            raise ValidationError("Cette preuve a déjà été traitée.")
    if decision not in allowed:
        raise ValidationError("Décision non autorisée.")
    evidence.status = decision
    evidence.save(update_fields=("status",))
    AuditEvent.objects.create(
        organization=evidence.organization, actor=actor, action=f"evidence.{decision}",
        target_type="evidence_record", target_id=str(evidence.pk),
        metadata={"version": evidence.version, "reason": reason},
    )
    return evidence


def can_collaborate(*, actor, project):
    return actor.is_authenticated and project.pk is not None


def can_read_document(*, actor, document):
    return document.status == ProjectDocument.Status.APPROVED


def can_preview_document(*, actor, document):
    if document.status == ProjectDocument.Status.APPROVED:
        return True
    if document.status == ProjectDocument.Status.VERIFIED:
        return actor.is_authenticated
    return (
        actor.is_authenticated
        and has_project_role(user=actor, project=document.project, roles=PROJECT_TECHNICAL_ROLES)
    )


@transaction.atomic
def review_document(*, actor, document, decision, reason):
    from apps.projects.disputes import ensure_decision_not_frozen
    from apps.projects.models import ProjectDispute

    ensure_decision_not_frozen(
        project=document.project, target_type=ProjectDispute.TargetType.DOCUMENT,
        target_id=document.pk,
    )
    if not can_manage_project(actor=actor, project=document.project):
        raise PermissionDenied
    if actor.is_superuser:
        if document.status != ProjectDocument.Status.VERIFIED:
            raise ValidationError("Seul un document vérifié par un ingénieur peut être traité.")
        allowed_decisions = {
            ProjectDocument.Status.APPROVED,
            ProjectDocument.Status.REJECTED,
        }
    else:
        if not has_project_role(
            user=actor, project=document.project, roles=PROJECT_TECHNICAL_ROLES
        ):
            raise PermissionDenied
        if document.status != ProjectDocument.Status.PENDING:
            raise ValidationError("Ce document a déjà été vérifié ou traité.")
        allowed_decisions = {
            ProjectDocument.Status.VERIFIED,
            ProjectDocument.Status.REJECTED,
        }
    if decision not in allowed_decisions:
        raise ValidationError("Décision invalide.")
    document.status = decision
    document.review_reason = reason
    document.reviewed_by = actor
    document.reviewed_at = timezone.now()
    document.save(update_fields=("status", "review_reason", "reviewed_by", "reviewed_at"))
    AuditEvent.objects.create(
        organization=document.organization,
        actor=actor,
        action=(
            "document.approved"
            if decision == ProjectDocument.Status.APPROVED
            else "document.reviewed"
        ),
        target_type="project_document",
        target_id=str(document.pk),
        metadata={"decision": decision, "reason": reason},
    )
    if document.uploaded_by_id != actor.pk:
        create_notification(
            recipient=document.uploaded_by,
            actor=actor,
            kind=Notification.Kind.DOCUMENT,
            title="Document examiné",
            message=f"{document.title} : {document.get_status_display()}.",
            target_url=f"{document.project.get_absolute_url()}?tab=documents",
            project=document.project,
        )


@transaction.atomic
def set_cover(*, actor, image):
    if not can_manage_project(actor=actor, project=image.project):
        raise PermissionDenied
    ProjectImage.objects.filter(project=image.project, is_cover=True).update(is_cover=False)
    image.is_cover = True
    image.save(update_fields=("is_cover",))
