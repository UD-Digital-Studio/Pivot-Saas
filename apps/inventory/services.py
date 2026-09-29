from decimal import Decimal
import hashlib
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.planning.services import can_manage_stages
from apps.projects.models import Project
from apps.projects.models import ProjectMembership
from apps.projects.access import has_project_role

from .models import (
    InventoryAnomaly, InventoryAnomalyResolution, InventoryExpectedRange,
    StockItem, StockMovement,
)


def can_adjust_stock(*, actor: User, project: Project) -> bool:
    return can_manage_stages(actor=actor, project=project)


def can_configure_expected_ranges(*, actor: User, project: Project) -> bool:
    return has_project_role(
        user=actor, project=project, roles={ProjectMembership.Role.ENGINEER}
    )


@transaction.atomic
def assign_expected_range(*, actor, item, existing_range=None, work_type="", unit="",
                          minimum_quantity=None, maximum_quantity=None, assumptions="",
                          out_of_range_action=""):
    if not can_configure_expected_ranges(actor=actor, project=item.project):
        raise PermissionDenied
    if existing_range:
        if (
            existing_range.project_id != item.project_id
            or existing_range.organization_id != item.organization_id
            or existing_range.unit != item.unit
        ):
            raise ValidationError("Cette plage ne peut pas être appliquée à cet article.")
        rule = existing_range
    else:
        previous = InventoryExpectedRange.objects.select_for_update().filter(
            project=item.project, work_type=work_type.strip(), unit=unit.strip()
        ).order_by("-version").first()
        rule = InventoryExpectedRange.objects.create(
            organization=item.organization, project=item.project,
            work_type=work_type.strip(), unit=unit.strip(),
            minimum_quantity=minimum_quantity, maximum_quantity=maximum_quantity,
            assumptions=assumptions.strip(),
            out_of_range_action=(out_of_range_action or InventoryExpectedRange.OutOfRangeAction.FLAG),
            version=(previous.version + 1 if previous else 1),
            supersedes=previous, created_by=actor,
        )
        if previous and previous.is_active:
            previous.is_active = False
            previous.save(update_fields=("is_active",))
    item.expected_range = rule
    item.save(update_fields=("expected_range", "updated_at"))
    AuditEvent.objects.create(
        organization=item.organization, actor=actor, action="stock.expected_range_assigned",
        target_type="stock_item", target_id=str(item.pk),
        metadata={"range_id": str(rule.pk), "version": rule.version,
                  "work_type": rule.work_type, "advisory_only": True},
    )
    return rule


@transaction.atomic
def detect_expense_inventory_anomalies(*, actor, expense_request):
    movements = list(
        StockMovement.objects.filter(
            project=expense_request.project, stage=expense_request.milestone,
            movement_type=StockMovement.Type.CONSUMED,
            item__expected_range__isnull=False,
        ).select_related("item__expected_range")
    )
    by_item = {}
    for movement in movements:
        by_item.setdefault(movement.item_id, []).append(movement)
    findings = []
    for item_movements in by_item.values():
        item = item_movements[0].item
        rule = item.expected_range
        observed = sum((movement.normalized_quantity for movement in item_movements), Decimal("0"))
        if rule.minimum_quantity <= observed <= rule.maximum_quantity:
            continue
        direction = (
            InventoryAnomaly.Direction.BELOW
            if observed < rule.minimum_quantity else InventoryAnomaly.Direction.ABOVE
        )
        movement_ids = sorted(str(movement.pk) for movement in item_movements)
        payload = "|".join((str(expense_request.pk), str(item.pk), str(rule.pk), str(observed), *movement_ids))
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        anomaly, created = InventoryAnomaly.objects.get_or_create(
            fingerprint=fingerprint,
            defaults={
                "organization": expense_request.organization, "project": expense_request.project,
                "expense_request": expense_request, "item": item, "expected_range": rule,
                "expected_range_version": rule.version,
                "minimum_snapshot": rule.minimum_quantity, "maximum_snapshot": rule.maximum_quantity,
                "observed_quantity": observed, "unit_snapshot": rule.unit,
                "direction": direction, "action": rule.out_of_range_action,
                "movement_ids": movement_ids,
            },
        )
        findings.append(anomaly)
        if created:
            AuditEvent.objects.create(
                organization=expense_request.organization, actor=actor,
                action="inventory.anomaly_detected", target_type="inventory_anomaly",
                target_id=str(anomaly.pk),
                metadata={"expense_request_id": str(expense_request.pk), "item_id": str(item.pk),
                          "range_version": rule.version, "direction": direction,
                          "action": rule.out_of_range_action},
            )
    return findings


ANOMALY_PARTICIPANT_ROLES = {
    ProjectMembership.Role.OWNER, ProjectMembership.Role.CONTRACTOR,
    ProjectMembership.Role.SITE_MANAGER, ProjectMembership.Role.ENGINEER,
    ProjectMembership.Role.PIVOT_REVIEWER,
}


def can_propose_anomaly_resolution(*, actor, anomaly):
    return anomaly.status == InventoryAnomaly.Status.OPEN and has_project_role(
        user=actor, project=anomaly.project, roles=ANOMALY_PARTICIPANT_ROLES
    )


def can_validate_anomaly_resolution(*, actor, anomaly):
    required_role = (
        ProjectMembership.Role.PIVOT_REVIEWER
        if anomaly.action == InventoryExpectedRange.OutOfRangeAction.BLOCK
        else ProjectMembership.Role.ENGINEER
    )
    return has_project_role(user=actor, project=anomaly.project, roles={required_role})


@transaction.atomic
def propose_anomaly_resolution(*, actor, anomaly, responsible, evidence, reason):
    anomaly = InventoryAnomaly.objects.select_for_update().get(pk=anomaly.pk)
    if not can_propose_anomaly_resolution(actor=actor, anomaly=anomaly):
        raise PermissionDenied
    if anomaly.resolutions.filter(status=InventoryAnomalyResolution.Status.PENDING).exists():
        raise ValidationError("Une proposition est déjà en attente de validation.")
    proofs = list(evidence)
    if not proofs:
        raise ValidationError("Au moins une preuve de résolution est obligatoire.")
    if any(proof.project_id != anomaly.project_id or proof.organization_id != anomaly.organization_id for proof in proofs):
        raise ValidationError("Toutes les preuves doivent appartenir au même projet.")
    resolution = InventoryAnomalyResolution.objects.create(
        anomaly=anomaly, responsible=responsible, reason=reason.strip(), proposed_by=actor,
    )
    resolution.evidence.set(proofs)
    AuditEvent.objects.create(
        organization=anomaly.organization, actor=actor,
        action="inventory.anomaly_resolution_proposed", target_type="inventory_anomaly_resolution",
        target_id=str(resolution.pk),
        metadata={"anomaly_id": str(anomaly.pk), "responsible_id": responsible.pk,
                  "evidence_ids": [str(proof.pk) for proof in proofs]},
    )
    return resolution


@transaction.atomic
def decide_anomaly_resolution(*, actor, resolution, decision, reason):
    resolution = InventoryAnomalyResolution.objects.select_for_update().select_related(
        "anomaly__project"
    ).get(pk=resolution.pk)
    if resolution.status != InventoryAnomalyResolution.Status.PENDING:
        raise ValidationError("Cette proposition a déjà reçu une décision.")
    if not can_validate_anomaly_resolution(actor=actor, anomaly=resolution.anomaly):
        raise PermissionDenied
    if decision not in {
        InventoryAnomalyResolution.Status.APPROVED,
        InventoryAnomalyResolution.Status.REJECTED,
    } or not reason.strip():
        raise ValidationError("La décision et son motif sont obligatoires.")
    resolution.status = decision
    resolution.decided_by = actor
    resolution.decision_reason = reason.strip()
    resolution.decided_at = timezone.now()
    resolution.save(update_fields=("status", "decided_by", "decision_reason", "decided_at"))
    if decision == InventoryAnomalyResolution.Status.APPROVED:
        anomaly = InventoryAnomaly.objects.select_for_update().get(pk=resolution.anomaly_id)
        anomaly.status = InventoryAnomaly.Status.RESOLVED
        anomaly.save(update_fields=("status",))
    AuditEvent.objects.create(
        organization=resolution.anomaly.organization, actor=actor,
        action="inventory.anomaly_resolution_decided", target_type="inventory_anomaly_resolution",
        target_id=str(resolution.pk),
        metadata={"anomaly_id": str(resolution.anomaly_id), "decision": decision,
                  "reason": reason.strip()},
    )
    return resolution


@transaction.atomic
def record_stock_movement(*, actor, item, movement_type, source_quantity, source_unit,
                          conversion_factor, source_reference, reason, idempotency_key,
                          evidence=None, stage=None):
    if not can_adjust_stock(actor=actor, project=item.project):
        raise PermissionDenied
    existing = StockMovement.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        if existing.item_id != item.pk or existing.actor_id != actor.pk:
            raise PermissionDenied
        return existing, False
    locked = StockItem.objects.select_for_update().get(pk=item.pk)
    if not locked.movements.exists() and locked.quantity:
        StockMovement.objects.create(
            organization=locked.organization, project=locked.project, item=locked,
            movement_type=StockMovement.Type.CORRECTION,
            source_reference="Stock d'ouverture", source_quantity=locked.quantity,
            source_unit=locked.unit, conversion_factor=Decimal("1"),
            normalized_quantity=abs(locked.quantity), variation=locked.quantity,
            resulting_quantity=locked.quantity, reason="Solde initial tracé automatiquement",
            actor=locked.created_by, idempotency_key=uuid.uuid4(),
        )
    source_quantity = Decimal(source_quantity)
    conversion_factor = Decimal(conversion_factor)
    if conversion_factor <= 0 or (
        movement_type != StockMovement.Type.CORRECTION and source_quantity <= 0
    ):
        raise ValidationError("La quantité et le facteur de conversion doivent être positifs.")
    normalized = abs(source_quantity * conversion_factor)
    if movement_type == StockMovement.Type.PURCHASED:
        variation = Decimal("0")
    elif movement_type == StockMovement.Type.DELIVERED:
        variation = normalized
    elif movement_type == StockMovement.Type.CONSUMED:
        variation = -normalized
    elif movement_type == StockMovement.Type.CORRECTION:
        variation = source_quantity * conversion_factor
    else:
        raise ValidationError("Nature de mouvement inconnue.")
    resulting = locked.derived_remaining_quantity + variation
    if resulting < 0:
        raise ValidationError("La quantité résultante ne peut pas être négative.")
    locked.quantity = resulting
    locked.save(update_fields=("quantity", "updated_at"))
    movement = StockMovement(
        organization=locked.organization,
        project=locked.project,
        item=locked,
        evidence=evidence,
        stage=stage,
        movement_type=movement_type,
        source_reference=source_reference,
        source_quantity=source_quantity,
        source_unit=source_unit,
        conversion_factor=conversion_factor,
        normalized_quantity=normalized,
        variation=variation,
        resulting_quantity=resulting,
        reason=reason,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    movement.full_clean()
    movement.save()
    return movement, True


def adjust_stock(*, actor, item, variation, reason, idempotency_key):
    """Compatibilité des corrections historiques."""
    return record_stock_movement(
        actor=actor, item=item, movement_type=StockMovement.Type.CORRECTION,
        source_quantity=Decimal(variation), source_unit=item.unit,
        conversion_factor=Decimal("1"), source_reference="Correction manuelle",
        reason=reason, idempotency_key=idempotency_key,
    )


@transaction.atomic
def verify_stock_item(*, actor, item):
    if not has_project_role(
        user=actor,
        project=item.project,
        roles={ProjectMembership.Role.ENGINEER, ProjectMembership.Role.PIVOT_REVIEWER},
    ):
        raise PermissionDenied
    item.status = StockItem.Status.VERIFIED
    item.verified_by = actor
    item.verified_at = timezone.now()
    item.save(update_fields=("status", "verified_by", "verified_at", "updated_at"))
    AuditEvent.objects.create(
        organization=item.organization,
        actor=actor,
        action="stock.item_verified",
        target_type="stock_item",
        target_id=str(item.pk),
        metadata={"status": item.status},
    )
    return item
