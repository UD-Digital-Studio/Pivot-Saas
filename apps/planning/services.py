from apps.accounts.models import User
from apps.projects.models import Project, ProjectMembership
from apps.projects.access import has_project_role, project_engineers
from apps.projects.services import can_manage_project
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.db import transaction
import hashlib
import json

from apps.audit.models import AuditEvent
from apps.accounts.models import Notification
from apps.accounts.services import create_notification
from .models import StageProgressDeclaration, StageProgressVerification, StageTechnicalReview, StageDigitalVerification, StageSiteVisit, StageSiteVerification, StageInspectionRiskRule, StageInspectionRiskAssessment


def can_manage_stages(*, actor: User, project: Project) -> bool:
    if can_manage_project(actor=actor, project=project):
        return True
    return has_project_role(
        user=actor,
        project=project,
        roles={ProjectMembership.Role.SITE_MANAGER},
    )


def declare_stage_progress(*, actor, stage, percent, evidence=None, note=""):
    if not can_manage_stages(actor=actor, project=stage.project):
        raise PermissionDenied
    record = StageProgressDeclaration.objects.create(
        organization=stage.organization, stage=stage, author=actor,
        percent=percent, evidence=evidence, note=note.strip(),
    )
    AuditEvent.objects.create(
        organization=stage.organization, actor=actor, action="stage.progress_declared",
        target_type="stage_progress_declaration", target_id=str(record.pk),
        metadata={"stage_id": str(stage.pk), "percent": record.percent, "evidence_id": str(evidence.pk) if evidence else None},
    )
    for engineer in project_engineers(stage.project).exclude(pk=actor.pk):
        create_notification(
            recipient=engineer, actor=actor, kind=Notification.Kind.PROJECT,
            title="Progression à examiner",
            message=f"{stage.project.name} · {stage.title} : {record.percent} % déclarés.",
            target_url=f"{stage.project.get_absolute_url()}?tab=stages",
            project=stage.project,
        )
    return record


def verify_stage_progress(*, actor, stage, percent, evidence=None, note="", quantities=None, reservations=None):
    is_authorized_engineer = (
        actor.is_superuser
        or has_project_role(user=actor, project=stage.project, roles={ProjectMembership.Role.ENGINEER})
    )
    if not is_authorized_engineer:
        raise PermissionDenied
    declaration = stage.latest_declared_progress
    if not declaration or not hasattr(declaration, "digital_verification"):
        raise ValidationError("Une vérification numérique réussie est requise.")
    if declaration.digital_verification.result != StageDigitalVerification.Result.PASSED:
        raise ValidationError("L'échec Digital Verified bloque la vérification de progression.")
    if hasattr(declaration, "technical_verification"):
        raise ValidationError("Cette déclaration possède déjà une vérification technique signée.")
    quantities = quantities or []
    reservations = reservations or []
    signed_at = timezone.now()
    signature_payload = {
        "actor_id": actor.pk,
        "declaration_id": str(declaration.pk),
        "digital_verification_id": str(declaration.digital_verification.pk),
        "percent": int(percent),
        "quantities": quantities,
        "reservations": reservations,
        "signed_at": signed_at.isoformat(),
    }
    logical_signature = hashlib.sha256(
        json.dumps(signature_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    record = StageProgressVerification.objects.create(
        organization=stage.organization, stage=stage, author=actor,
        declaration=declaration, digital_verification=declaration.digital_verification,
        percent=percent, evidence=declaration.evidence, note=note.strip(),
        quantities=quantities, reservations=reservations,
        logical_signature=logical_signature, signed_at=signed_at,
    )
    AuditEvent.objects.create(
        organization=stage.organization, actor=actor, action="stage.progress_verified",
        target_type="stage_progress_verification", target_id=str(record.pk),
        metadata={
            "stage_id": str(stage.pk), "declaration_id": str(declaration.pk),
            "digital_verification_id": str(declaration.digital_verification.pk),
            "percent": record.percent, "evidence_id": str(record.evidence_id) if record.evidence_id else None,
            "quantities": record.quantities, "reservations": record.reservations,
            "logical_signature": record.logical_signature, "signed_at": record.signed_at.isoformat(),
        },
    )
    return record


def review_stage_progress(*, actor, declaration, decision, reason, corrective_actions=""):
    stage = declaration.stage
    if not (
        actor.is_superuser
        or has_project_role(
            user=actor,
            project=stage.project,
            roles={ProjectMembership.Role.ENGINEER},
        )
    ):
        raise PermissionDenied
    if hasattr(declaration, "technical_review"):
        raise ValidationError("Cette déclaration possède déjà une décision technique.")
    review = StageTechnicalReview.objects.create(
        organization=declaration.organization, declaration=declaration, reviewer=actor,
        decision=decision, reason=reason.strip(), corrective_actions=corrective_actions.strip(),
    )
    AuditEvent.objects.create(
        organization=declaration.organization, actor=actor, action="stage.progress_technical_reviewed",
        target_type="stage_technical_review", target_id=str(review.pk),
        metadata={"declaration_id": str(declaration.pk), "decision": decision, "percent": declaration.percent},
    )
    if declaration.author_id != actor.pk:
        create_notification(
            recipient=declaration.author, actor=actor, kind=Notification.Kind.PROJECT,
            title="Avis technique sur votre progression",
            message=f"{stage.project.name} · {stage.title} : {review.get_decision_display()}.",
            target_url=f"{stage.project.get_absolute_url()}?tab=stages",
            project=stage.project,
        )
    return review


def run_stage_digital_verification(*, actor, declaration):
    stage = declaration.stage
    if not (
        actor.is_superuser
        or has_project_role(
            user=actor,
            project=stage.project,
            roles={ProjectMembership.Role.ENGINEER, ProjectMembership.Role.PIVOT_REVIEWER},
        )
    ):
        raise PermissionDenied
    if hasattr(declaration, "digital_verification"):
        raise ValidationError("Cette version a déjà été contrôlée numériquement.")

    evidence = declaration.evidence
    author_is_assigned = (
        ProjectMembership.objects.filter(project=stage.project, user=declaration.author).exists()
    )
    evidence_author_is_assigned = bool(
        evidence and (
            ProjectMembership.objects.filter(project=stage.project, user=evidence.author).exists()
        )
    )
    technical_review = getattr(declaration, "technical_review", None)
    checks = {
        "evidence_present": evidence is not None,
        "chronology_valid": bool(evidence and evidence.captured_at <= declaration.created_at),
        "declaration_actor_assigned": author_is_assigned,
        "evidence_actor_assigned": evidence_author_is_assigned,
        "organization_consistent": bool(evidence and evidence.organization_id == declaration.organization_id),
        "project_consistent": bool(evidence and evidence.project_id == stage.project_id),
        "stage_consistent": bool(evidence and evidence.stage_id in {None, stage.pk}),
        "evidence_not_rejected": bool(evidence and evidence.status != evidence.Status.REJECTED),
        "technical_review_acceptable": bool(
            technical_review and technical_review.decision != StageTechnicalReview.Decision.REJECTED
        ),
    }
    examined_items = {
        "declaration": {"id": str(declaration.pk), "percent": declaration.percent, "author_id": declaration.author_id},
        "evidence": ({
            "id": str(evidence.pk), "key": str(evidence.evidence_key), "version": evidence.version,
            "status": evidence.status, "type": evidence.evidence_type,
            "author_id": evidence.author_id, "captured_at": evidence.captured_at.isoformat(),
        } if evidence else None),
        "technical_review": ({
            "id": str(technical_review.pk), "decision": technical_review.decision,
            "reviewer_id": technical_review.reviewer_id,
        } if technical_review else None),
    }
    result = (
        StageDigitalVerification.Result.PASSED
        if all(checks.values()) else StageDigitalVerification.Result.FAILED
    )
    verification = StageDigitalVerification.objects.create(
        organization=declaration.organization, declaration=declaration, initiated_by=actor,
        result=result, checks=checks, examined_items=examined_items,
    )
    AuditEvent.objects.create(
        organization=declaration.organization, actor=actor, action="stage.progress_digital_verified",
        target_type="stage_digital_verification", target_id=str(verification.pk),
        metadata={"declaration_id": str(declaration.pk), "result": result, "checks": checks},
    )
    return verification


def can_run_site_inspection(*, actor, project):
    return actor.is_superuser or has_project_role(
        user=actor, project=project, roles={ProjectMembership.Role.PIVOT_REVIEWER}
    )


def record_stage_site_visit(*, actor, stage, visited_at, location_label="", latitude=None, longitude=None, notes=""):
    if not can_run_site_inspection(actor=actor, project=stage.project):
        raise PermissionDenied
    visit = StageSiteVisit.objects.create(
        organization=stage.organization, stage=stage, inspector=actor,
        visited_at=visited_at, location_label=location_label.strip(), latitude=latitude,
        longitude=longitude, notes=notes.strip(),
    )
    AuditEvent.objects.create(
        organization=stage.organization, actor=actor, action="stage.site_visit_recorded",
        target_type="stage_site_visit", target_id=str(visit.pk),
        metadata={"stage_id": str(stage.pk), "visited_at": visit.visited_at.isoformat(), "location": visit.location_label},
    )
    return visit


@transaction.atomic
def complete_stage_site_verification(*, actor, visit, technical_verification, checklist, evidence, reservations, result):
    if not can_run_site_inspection(actor=actor, project=visit.stage.project):
        raise PermissionDenied
    if visit.inspector_id != actor.pk and not actor.is_superuser:
        raise PermissionDenied("Seul l'inspecteur ayant enregistré la visite peut la conclure.")
    if hasattr(visit, "verification"):
        raise ValidationError("Cette visite possède déjà une conclusion.")
    evidence = list(evidence)
    if not evidence:
        raise ValidationError("Une inspection doit référencer au moins une preuve.")
    if any(
        item.organization_id != visit.organization_id
        or item.project_id != visit.stage.project_id
        or item.stage_id not in {None, visit.stage_id}
        for item in evidence
    ):
        raise ValidationError("Toutes les preuves doivent appartenir à l'étape visitée.")
    inspection = StageSiteVerification(
        organization=visit.organization, visit=visit,
        technical_verification=technical_verification, inspector=actor,
        checklist=checklist, reservations=reservations or [], result=result,
    )
    inspection.full_clean()
    inspection.save()
    inspection.evidence.set(evidence)
    AuditEvent.objects.create(
        organization=visit.organization, actor=actor, action="stage.site_verified",
        target_type="stage_site_verification", target_id=str(inspection.pk),
        metadata={
            "visit_id": str(visit.pk), "stage_id": str(visit.stage_id), "result": result,
            "evidence_ids": [str(item.pk) for item in evidence], "checklist": checklist,
            "reservations": reservations or [], "visited_at": visit.visited_at.isoformat(),
            "latitude": str(visit.latitude) if visit.latitude is not None else None,
            "longitude": str(visit.longitude) if visit.longitude is not None else None,
        },
    )
    return inspection


def create_inspection_risk_rule(*, actor, organization, data):
    if not actor.is_superuser:
        raise PermissionDenied
    with transaction.atomic():
        current = StageInspectionRiskRule.objects.select_for_update().filter(organization=organization, is_active=True)
        version = (StageInspectionRiskRule.objects.filter(organization=organization).order_by("-version").values_list("version", flat=True).first() or 0) + 1
        current.update(is_active=False)
        rule = StageInspectionRiskRule.objects.create(
            organization=organization,
            version=version,
            created_by=actor,
            stage_types=data.get("stage_types", []),
            require_on_anomaly=True,
        )
        AuditEvent.objects.create(organization=organization, actor=actor, action="stage.inspection_risk_rule_versioned", target_type="stage_inspection_risk_rule", target_id=str(rule.pk), metadata={"version": version})
        return rule


def evaluate_stage_inspection_risk(*, actor, technical_verification):
    stage = technical_verification.stage
    if not (actor.is_superuser or has_project_role(user=actor, project=stage.project, roles={ProjectMembership.Role.ENGINEER, ProjectMembership.Role.PIVOT_REVIEWER})):
        raise PermissionDenied
    if hasattr(technical_verification, "risk_assessment"):
        return technical_verification.risk_assessment
    rule = StageInspectionRiskRule.objects.filter(organization=stage.organization, is_active=True).first()
    if not rule:
        raise ValidationError("Aucune règle de risque active n'est configurée pour cette organisation.")
    declaration = technical_verification.declaration
    variance = abs((declaration.percent if declaration else 0) - technical_verification.percent)
    anomaly = bool(variance > rule.maximum_progress_variance or technical_verification.reservations)
    reasons = []
    if stage.stage_type in rule.stage_types:
        reasons.append("type_de_jalon")
    if anomaly:
        reasons.append("anomalie")
    assessment = StageInspectionRiskAssessment.objects.create(
        organization=stage.organization, technical_verification=technical_verification,
        rule=rule, inspection_required=bool(reasons), reasons=reasons, evaluated_by=actor,
    )
    AuditEvent.objects.create(organization=stage.organization, actor=actor, action="stage.inspection_risk_evaluated", target_type="stage_inspection_risk_assessment", target_id=str(assessment.pk), metadata={"rule_version": rule.version, "required": assessment.inspection_required, "reasons": reasons, "variance": variance})
    return assessment


def inspection_requirement_is_satisfied(stage):
    technical = stage.latest_verified_progress
    if not technical or not hasattr(technical, "risk_assessment"):
        return True
    assessment = technical.risk_assessment
    if not assessment.inspection_required:
        return True
    return StageSiteVerification.objects.filter(
        technical_verification=technical,
        result__in={StageSiteVerification.Result.PASSED, StageSiteVerification.Result.CONDITIONAL},
    ).exists()
