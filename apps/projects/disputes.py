from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.collaboration.models import EvidenceRecord, ProjectDocument
from apps.finance.models import ExpenseRequest
from apps.inventory.models import InventoryAnomaly

from .models import (
    ProjectDispute, ProjectDisputeEvidence, ProjectDisputeObservation,
)


TARGET_MODELS = {
    ProjectDispute.TargetType.DOCUMENT: ProjectDocument,
    ProjectDispute.TargetType.EXPENSE_REQUEST: ExpenseRequest,
    ProjectDispute.TargetType.EVIDENCE: EvidenceRecord,
    ProjectDispute.TargetType.INVENTORY_ANOMALY: InventoryAnomaly,
}


def _is_participant(actor, project):
    return actor.is_superuser or project.memberships.filter(user=actor).exists()


def ensure_decision_not_frozen(*, project, target_type, target_id):
    if ProjectDispute.objects.filter(
        project=project, target_type=target_type, target_id=target_id,
        status=ProjectDispute.Status.OPEN, freezes_decision=True,
    ).exists():
        raise ValidationError("Cette décision est gelée par une contestation ouverte.")


@transaction.atomic
def open_dispute(*, actor, project, target_type, target_id, subject, reason,
                 freezes_decision=False, evidence=()):
    if not _is_participant(actor, project):
        raise PermissionDenied
    model = TARGET_MODELS.get(target_type)
    if model is None or not model.objects.filter(
        pk=target_id, project=project, organization=project.organization
    ).exists():
        raise ValidationError("L’objet contesté n’appartient pas à ce chantier.")
    if freezes_decision and not actor.is_superuser:
        raise PermissionDenied("Seul PIVOT peut imposer le gel d’une décision.")
    dispute = ProjectDispute.objects.create(
        organization=project.organization, project=project, target_type=target_type,
        target_id=target_id, subject=subject.strip(), reason=reason.strip(),
        freezes_decision=freezes_decision, raised_by=actor,
    )
    for item in evidence:
        if item.project_id != project.pk or item.organization_id != project.organization_id:
            raise ValidationError("Une preuve jointe appartient à un autre chantier.")
        ProjectDisputeEvidence.objects.create(dispute=dispute, evidence=item, attached_by=actor)
    AuditEvent.objects.create(
        organization=project.organization, actor=actor, action="project.dispute_opened",
        target_type="project_dispute", target_id=str(dispute.pk), metadata={
            "project_id": str(project.pk), "target_type": target_type,
            "target_id": str(target_id), "freezes_decision": freezes_decision,
            "evidence_ids": [str(item.pk) for item in evidence],
        },
    )
    return dispute


def add_dispute_observation(*, actor, dispute, position, body):
    if not _is_participant(actor, dispute.project):
        raise PermissionDenied
    if dispute.status != ProjectDispute.Status.OPEN:
        raise ValidationError("Cette contestation est déjà résolue.")
    if position not in ProjectDisputeObservation.Position.values or not body.strip():
        raise ValidationError("La position et l’observation sont obligatoires.")
    observation = ProjectDisputeObservation.objects.create(
        dispute=dispute, author=actor, position=position, body=body.strip()
    )
    AuditEvent.objects.create(
        organization=dispute.organization, actor=actor,
        action="project.dispute_observation_added", target_type="project_dispute",
        target_id=str(dispute.pk), metadata={"position": position},
    )
    return observation


@transaction.atomic
def resolve_dispute(*, actor, dispute, resolution):
    if not actor.is_superuser:
        raise PermissionDenied
    locked = ProjectDispute.objects.select_for_update().get(pk=dispute.pk)
    if locked.status == ProjectDispute.Status.RESOLVED:
        return locked
    if not resolution.strip():
        raise ValidationError("La résolution motivée est obligatoire.")
    locked.status = ProjectDispute.Status.RESOLVED
    locked.resolution = resolution.strip()
    locked.resolved_by = actor
    locked.resolved_at = timezone.now()
    locked.save(update_fields=("status", "resolution", "resolved_by", "resolved_at"))
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor, action="project.dispute_resolved",
        target_type="project_dispute", target_id=str(locked.pk), metadata={
            "resolution": locked.resolution, "evidence_preserved": True,
        },
    )
    return locked
