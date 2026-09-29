from decimal import Decimal
import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Notification, User
from apps.accounts.services import create_notification
from apps.audit.models import AuditEvent
from apps.projects.models import ProjectMembership
from apps.projects.access import (
    can_authorize_project_finance,
    can_monitor_project_finance,
    is_project_owner,
    has_project_role,
    project_engineers,
)
from apps.projects.services import can_manage_project, project_finance_is_unlocked

from .gateways import configured_gateway
from .models import ExpenseOwnerDecision, ExpensePivotVerification, ExpenseRequest, ExpenseRequestAttachment, ExpenseRequestTransition, ExpenseTechnicalOpinion, PaymentTransaction, Withdrawal
from apps.collaboration.models import EvidenceRecord


EXPENSE_FLOW = {
    ExpenseRequest.Status.DRAFT: {ExpenseRequest.Status.SUBMITTED},
    ExpenseRequest.Status.SUBMITTED: {ExpenseRequest.Status.EVIDENCE},
    ExpenseRequest.Status.EVIDENCE: {ExpenseRequest.Status.REVIEW},
    ExpenseRequest.Status.REVIEW: {ExpenseRequest.Status.VERIFIED, ExpenseRequest.Status.REJECTED},
    ExpenseRequest.Status.VERIFIED: {ExpenseRequest.Status.AUTHORIZED, ExpenseRequest.Status.REJECTED},
    ExpenseRequest.Status.AUTHORIZED: {ExpenseRequest.Status.CLOSED},
    ExpenseRequest.Status.REJECTED: set(),
    ExpenseRequest.Status.CLOSED: set(),
}

EXPENSE_EVIDENCE_TYPES = {
    ExpenseRequestAttachment.DocumentType.INVOICE: {EvidenceRecord.Type.INVOICE},
    ExpenseRequestAttachment.DocumentType.QUOTE: {EvidenceRecord.Type.QUOTE},
    ExpenseRequestAttachment.DocumentType.DELIVERY_NOTE: {EvidenceRecord.Type.DELIVERY_NOTE},
    ExpenseRequestAttachment.DocumentType.FIELD_EVIDENCE: {
        EvidenceRecord.Type.PHOTO, EvidenceRecord.Type.VIDEO, EvidenceRecord.Type.INSPECTION,
        EvidenceRecord.Type.MINUTES, EvidenceRecord.Type.DOCUMENT,
    },
    ExpenseRequestAttachment.DocumentType.WORK_EVIDENCE: {
        EvidenceRecord.Type.PHOTO, EvidenceRecord.Type.VIDEO,
        EvidenceRecord.Type.INSPECTION, EvidenceRecord.Type.MINUTES,
    },
    ExpenseRequestAttachment.DocumentType.PROGRESS_EVIDENCE: {
        EvidenceRecord.Type.PHOTO, EvidenceRecord.Type.VIDEO,
        EvidenceRecord.Type.INSPECTION, EvidenceRecord.Type.MINUTES,
    },
}


def _notify_expense_roles(*, expense_request, actor, roles, title, message):
    recipients = User.objects.filter(
        project_memberships__project=expense_request.project,
        project_memberships__project_role__in=set(roles),
    ).exclude(pk=actor.pk).distinct()
    for recipient in recipients:
        create_notification(
            recipient=recipient, actor=actor, kind=Notification.Kind.FINANCE,
            title=title, message=message,
            target_url=f"{expense_request.project.get_absolute_url()}?tab=expenses",
            project=expense_request.project,
        )


def required_expense_documents(expense_request):
    rules = {
        ExpenseRequest.Type.MATERIAL: {"quote", "invoice"},
        ExpenseRequest.Type.LABOR: {"quote", "field_evidence"},
        ExpenseRequest.Type.SERVICE: {"quote", "invoice"},
        ExpenseRequest.Type.EQUIPMENT: {"quote", "invoice"},
        ExpenseRequest.Type.OTHER: {"quote"},
    }
    required = set(rules[expense_request.expense_type])
    if expense_request.amount >= Decimal("500000") and expense_request.expense_type in {ExpenseRequest.Type.MATERIAL, ExpenseRequest.Type.EQUIPMENT}:
        required.add("delivery_note")
    elif expense_request.amount >= Decimal("500000"):
        required.add("invoice")
    return required


def missing_expense_documents(expense_request):
    available = set(
        expense_request.attachments.filter(
            status=ExpenseRequestAttachment.Status.ACTIVE
        ).exclude(evidence__status=EvidenceRecord.Status.REJECTED).values_list("document_type", flat=True)
    )
    return required_expense_documents(expense_request) - available


def expense_dossier_is_complete(expense_request):
    return not missing_expense_documents(expense_request)


def evaluate_expense_risk(expense_request, *, persist=True):
    score, reasons = 0, []
    if expense_request.amount >= Decimal("1000000"):
        score += 50
        reasons.append("Montant supérieur ou égal à 1 000 000 XAF")
    elif expense_request.amount >= Decimal("500000"):
        score += 35
        reasons.append("Montant supérieur ou égal à 500 000 XAF")
    elif expense_request.amount >= Decimal("250000"):
        score += 20
        reasons.append("Montant supérieur ou égal à 250 000 XAF")
    if expense_request.expense_type in {ExpenseRequest.Type.MATERIAL, ExpenseRequest.Type.EQUIPMENT}:
        score += 15
        reasons.append("Dépense de matériaux ou d’équipement")
    opinion = expense_request.technical_opinions.filter(is_current=True).first()
    if opinion and opinion.decision == ExpenseTechnicalOpinion.Decision.CONDITIONAL:
        score += 35
        reasons.append("Avis technique conditionnel")
    level = "high" if score >= 50 else "medium" if score >= 35 else "low"
    required = score >= 35
    if persist:
        ExpenseRequest.objects.filter(pk=expense_request.pk).update(
            risk_score=score, risk_level=level,
            pivot_review_required=required, risk_reasons=reasons,
        )
        expense_request.risk_score = score
        expense_request.risk_level = level
        expense_request.pivot_review_required = required
        expense_request.risk_reasons = reasons
    return {"score": score, "level": level, "required": required, "reasons": reasons}


def expense_dossier_inconsistencies(expense_request):
    issues = []
    if not expense_dossier_is_complete(expense_request):
        issues.append("Pièces obligatoires manquantes")
    if expense_request.attachments.filter(
        status=ExpenseRequestAttachment.Status.ACTIVE, evidence__stage__isnull=False,
    ).exclude(evidence__stage=expense_request.milestone).exists():
        issues.append("Une preuve terrain concerne un autre jalon")
    opinion = expense_request.technical_opinions.filter(is_current=True).first()
    if expense_request.status in {ExpenseRequest.Status.VERIFIED, ExpenseRequest.Status.AUTHORIZED}:
        if not opinion or opinion.decision not in {
            ExpenseTechnicalOpinion.Decision.APPROVED,
            ExpenseTechnicalOpinion.Decision.CONDITIONAL,
        }:
            issues.append("Avis technique valide absent")
        elif opinion.reviewed_status_version != expense_request.status_version - 1:
            issues.append("L’avis technique ne correspond pas à la version du dossier")
    return issues


def _rewind_expense_for_substantive_change(*, expense_request, actor, reason, supersede_opinion=True):
    locked = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
    if supersede_opinion:
        now = timezone.now()
        ExpenseTechnicalOpinion.objects.filter(request=locked, is_current=True).update(
            is_current=False, superseded_at=now
        )
        ExpensePivotVerification.objects.filter(request=locked, is_current=True).update(
            is_current=False, superseded_at=now
        )
    if locked.status not in {ExpenseRequest.Status.REVIEW, ExpenseRequest.Status.VERIFIED}:
        return locked
    previous_status = locked.status
    locked.status = ExpenseRequest.Status.EVIDENCE
    locked.status_version += 1
    locked.save(update_fields=("status", "status_version", "updated_at"))
    ExpenseRequestTransition.objects.create(
        request=locked, actor=actor, previous_status=previous_status,
        new_status=ExpenseRequest.Status.EVIDENCE, reason=reason,
        status_version=locked.status_version,
    )
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor,
        action="expense_request.review_reopened", target_type="expense_request",
        target_id=str(locked.pk),
        metadata={
            "previous_status": previous_status, "new_status": locked.status,
            "status_version": locked.status_version, "reason": reason,
        },
    )
    return locked


def can_create_expense_request(*, actor, project):
    return actor.is_superuser or has_project_role(
        user=actor, project=project, roles={ProjectMembership.Role.CONTRACTOR}
    )


def allowed_expense_transitions(*, actor, expense_request):
    candidates = EXPENSE_FLOW.get(expense_request.status, set())
    if expense_request.status == ExpenseRequest.Status.REVIEW:
        # La sortie de revue passe obligatoirement par un avis technique motivé.
        return set()
    if expense_request.status == ExpenseRequest.Status.VERIFIED:
        # Aucun rôle, y compris superuser, ne contourne la décision du propriétaire.
        return set()
    if actor.is_superuser:
        return candidates
    if expense_request.status in {ExpenseRequest.Status.DRAFT, ExpenseRequest.Status.SUBMITTED, ExpenseRequest.Status.EVIDENCE}:
        return candidates if actor.pk == expense_request.author_id and has_project_role(user=actor, project=expense_request.project, roles={ProjectMembership.Role.CONTRACTOR}) else set()
    if expense_request.status == ExpenseRequest.Status.AUTHORIZED:
        return candidates if can_authorize_project_finance(user=actor, project=expense_request.project) else set()
    return set()


@transaction.atomic
def create_expense_request(*, actor, project, data):
    if not can_create_expense_request(actor=actor, project=project):
        raise PermissionDenied
    expense_request = ExpenseRequest.objects.create(
        organization=project.organization, project=project, author=actor,
        milestone=data["milestone"], expense_type=data.get("expense_type", ExpenseRequest.Type.OTHER), amount=data["amount"], currency=data["currency"].upper(),
        purpose=data["purpose"].strip(), beneficiary=data["beneficiary"].strip(), due_date=data["due_date"],
    )
    AuditEvent.objects.create(
        organization=project.organization, actor=actor, action="expense_request.created",
        target_type="expense_request", target_id=str(expense_request.pk),
        metadata={"status": expense_request.status, "amount": str(expense_request.amount), "currency": expense_request.currency, "milestone_id": str(expense_request.milestone_id)},
    )
    if data.get("create_mode") == ExpenseRequest.Status.SUBMITTED:
        expense_request = transition_expense_request(
            actor=actor, expense_request=expense_request,
            target_status=ExpenseRequest.Status.SUBMITTED,
            expected_version=expense_request.status_version,
            reason="Soumission initiale",
        )
    return expense_request


@transaction.atomic
def transition_expense_request(*, actor, expense_request, target_status, expected_version, reason=""):
    locked = ExpenseRequest.objects.select_for_update().select_related("project").get(pk=expense_request.pk)
    from apps.projects.disputes import ensure_decision_not_frozen
    from apps.projects.models import ProjectDispute

    ensure_decision_not_frozen(
        project=locked.project, target_type=ProjectDispute.TargetType.EXPENSE_REQUEST,
        target_id=locked.pk,
    )
    if locked.status_version != expected_version:
        raise ValidationError("La demande a changé. Actualisez la page avant de continuer.")
    if target_status not in allowed_expense_transitions(actor=actor, expense_request=locked):
        raise PermissionDenied
    if target_status in {
        ExpenseRequest.Status.REVIEW,
        ExpenseRequest.Status.VERIFIED,
        ExpenseRequest.Status.AUTHORIZED,
    } and not expense_dossier_is_complete(locked):
        raise ValidationError("Le dossier est incomplet. Ajoutez toutes les pièces obligatoires.")
    if target_status == ExpenseRequest.Status.AUTHORIZED:
        risk = evaluate_expense_risk(locked)
        issues = expense_dossier_inconsistencies(locked)
        if issues:
            raise ValidationError("Le dossier est incohérent : " + "; ".join(issues) + ".")
        if risk["required"]:
            verification = locked.pivot_verifications.filter(is_current=True).first()
            if not verification or verification.decision != ExpensePivotVerification.Decision.APPROVED:
                raise ValidationError("La vérification PIVOT est obligatoire avant l’autorisation.")
            if verification.reviewed_status_version != locked.status_version:
                raise ValidationError("La vérification PIVOT ne correspond plus à la version actuelle du dossier.")
    previous_status = locked.status
    reason = reason.strip() or f"Passage de {locked.get_status_display()} vers {dict(ExpenseRequest.Status.choices)[target_status]}"
    locked.status = target_status
    locked.status_version += 1
    locked.save(update_fields=("status", "status_version", "updated_at"))
    ExpenseRequestTransition.objects.create(
        request=locked, actor=actor, previous_status=previous_status,
        new_status=target_status, reason=reason, status_version=locked.status_version,
    )
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor, action="expense_request.transitioned",
        target_type="expense_request", target_id=str(locked.pk),
        metadata={"previous_status": previous_status, "new_status": target_status, "status_version": locked.status_version, "reason": reason},
    )
    if target_status == ExpenseRequest.Status.REVIEW:
        _notify_expense_roles(
            expense_request=locked, actor=actor,
            roles={ProjectMembership.Role.ENGINEER},
            title="Demande de dépense à examiner",
            message=f"{locked.project.name} · {locked.purpose} · version {locked.status_version}.",
        )
    return locked


def _can_manage_expense_dossier(actor, expense_request):
    return actor.is_superuser or (
        actor.pk == expense_request.author_id
        and expense_request.status in {
            ExpenseRequest.Status.DRAFT,
            ExpenseRequest.Status.SUBMITTED,
            ExpenseRequest.Status.EVIDENCE,
            ExpenseRequest.Status.REVIEW,
            ExpenseRequest.Status.VERIFIED,
        }
        and has_project_role(user=actor, project=expense_request.project, roles={ProjectMembership.Role.CONTRACTOR})
    )


def _validate_attachment_evidence(document_type, evidence, expense_request):
    if evidence.project_id != expense_request.project_id or evidence.organization_id != expense_request.organization_id:
        raise ValidationError("Cette preuve appartient à un autre projet.")
    if evidence.evidence_type not in EXPENSE_EVIDENCE_TYPES[document_type]:
        raise ValidationError("Le type de la preuve ne correspond pas à la nature choisie.")


@transaction.atomic
def attach_expense_evidence(*, actor, expense_request, document_type, evidence):
    expense_request = ExpenseRequest.objects.select_for_update().get(pk=expense_request.pk)
    if not _can_manage_expense_dossier(actor, expense_request):
        raise PermissionDenied
    _validate_attachment_evidence(document_type, evidence, expense_request)
    attachment = ExpenseRequestAttachment.objects.create(
        organization=expense_request.organization, request=expense_request, evidence=evidence,
        document_type=document_type, added_by=actor,
    )
    AuditEvent.objects.create(
        organization=expense_request.organization, actor=actor, action="expense_request.attachment_added",
        target_type="expense_request_attachment", target_id=str(attachment.pk),
        metadata={"request_id": str(expense_request.pk), "evidence_id": str(evidence.pk), "document_type": document_type, "evidence_version": evidence.version},
    )
    _rewind_expense_for_substantive_change(
        expense_request=expense_request, actor=actor,
        reason="Ajout d’une pièce après revue",
    )
    return attachment


@transaction.atomic
def reject_expense_attachment(*, actor, attachment, reason):
    attachment = ExpenseRequestAttachment.objects.select_for_update().select_related("request__project").get(pk=attachment.pk)
    if not has_project_role(user=actor, project=attachment.request.project, roles={ProjectMembership.Role.ENGINEER, ProjectMembership.Role.PIVOT_REVIEWER}):
        raise PermissionDenied
    if attachment.status != ExpenseRequestAttachment.Status.ACTIVE or not reason.strip():
        raise ValidationError("Cette pièce ne peut pas être rejetée sans motif.")
    attachment.status = ExpenseRequestAttachment.Status.REJECTED
    attachment.reason = reason.strip()
    attachment.decided_at = timezone.now()
    attachment.save(update_fields=("status", "reason", "decided_at"))
    AuditEvent.objects.create(organization=attachment.organization, actor=actor, action="expense_request.attachment_rejected", target_type="expense_request_attachment", target_id=str(attachment.pk), metadata={"request_id": str(attachment.request_id), "reason": attachment.reason})
    _rewind_expense_for_substantive_change(
        expense_request=attachment.request, actor=actor,
        reason="Pièce rejetée après revue technique",
    )
    return attachment


@transaction.atomic
def replace_expense_attachment(*, actor, attachment, replacement_evidence, reason):
    attachment = ExpenseRequestAttachment.objects.select_for_update().select_related("request__project").get(pk=attachment.pk)
    if not _can_manage_expense_dossier(actor, attachment.request):
        raise PermissionDenied
    if attachment.status not in {
        ExpenseRequestAttachment.Status.ACTIVE,
        ExpenseRequestAttachment.Status.REJECTED,
    } or not reason.strip():
        raise ValidationError("Le remplacement exige une pièce active ou rejetée et un motif.")
    _validate_attachment_evidence(attachment.document_type, replacement_evidence, attachment.request)
    replacement = ExpenseRequestAttachment.objects.create(
        organization=attachment.organization, request=attachment.request, evidence=replacement_evidence,
        document_type=attachment.document_type, added_by=actor, reason=reason.strip(),
    )
    attachment.status = ExpenseRequestAttachment.Status.REPLACED
    attachment.reason = reason.strip()
    attachment.replaced_by = replacement
    attachment.decided_at = timezone.now()
    attachment.save(update_fields=("status", "reason", "replaced_by", "decided_at"))
    AuditEvent.objects.create(organization=attachment.organization, actor=actor, action="expense_request.attachment_replaced", target_type="expense_request_attachment", target_id=str(attachment.pk), metadata={"request_id": str(attachment.request_id), "replacement_id": str(replacement.pk), "reason": attachment.reason})
    _rewind_expense_for_substantive_change(
        expense_request=attachment.request, actor=actor,
        reason="Remplacement d’une pièce après revue",
    )
    return replacement


@transaction.atomic
def submit_expense_technical_opinion(*, actor, expense_request, decision, reason, expected_version):
    locked = ExpenseRequest.objects.select_for_update().select_related("project").get(pk=expense_request.pk)
    if locked.status_version != expected_version:
        raise ValidationError("La demande a changé. Actualisez la page avant de rendre votre avis.")
    if locked.status != ExpenseRequest.Status.REVIEW:
        raise ValidationError("L’avis technique ne peut être rendu que pendant la revue.")
    if not actor.is_superuser and not has_project_role(
        user=actor, project=locked.project, roles={ProjectMembership.Role.ENGINEER}
    ):
        raise PermissionDenied
    if decision not in ExpenseTechnicalOpinion.Decision.values or not reason.strip():
        raise ValidationError("La décision et son motif sont obligatoires.")
    if not expense_dossier_is_complete(locked):
        raise ValidationError("Le dossier est incomplet. L’avis technique ne peut pas être rendu.")

    ExpenseTechnicalOpinion.objects.filter(request=locked, is_current=True).update(
        is_current=False, superseded_at=timezone.now()
    )
    opinion = ExpenseTechnicalOpinion.objects.create(
        organization=locked.organization, request=locked, engineer=actor,
        decision=decision, reason=reason.strip(),
        reviewed_status_version=locked.status_version,
    )
    if decision == ExpenseTechnicalOpinion.Decision.REJECTED:
        updated = _rewind_expense_for_substantive_change(
            expense_request=locked, actor=actor,
            reason="Avis technique rejeté : retour aux preuves",
            supersede_opinion=False,
        )
    else:
        previous_status = locked.status
        locked.status = ExpenseRequest.Status.VERIFIED
        locked.status_version += 1
        locked.save(update_fields=("status", "status_version", "updated_at"))
        ExpenseRequestTransition.objects.create(
            request=locked, actor=actor, previous_status=previous_status,
            new_status=locked.status,
            reason=f"Avis technique {opinion.get_decision_display().lower()} : {opinion.reason}",
            status_version=locked.status_version,
        )
        AuditEvent.objects.create(
            organization=locked.organization, actor=actor,
            action="expense_request.transitioned", target_type="expense_request",
            target_id=str(locked.pk),
            metadata={
                "previous_status": previous_status, "new_status": locked.status,
                "status_version": locked.status_version, "technical_opinion_id": str(opinion.pk),
            },
        )
        updated = locked
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor,
        action="expense_request.technical_opinion_submitted",
        target_type="expense_technical_opinion", target_id=str(opinion.pk),
        metadata={
            "request_id": str(locked.pk), "decision": decision,
            "reviewed_status_version": opinion.reviewed_status_version,
            "resulting_request_status": updated.status,
        },
    )
    evaluate_expense_risk(updated)
    if updated.status == ExpenseRequest.Status.VERIFIED:
        from apps.inventory.services import detect_expense_inventory_anomalies
        detect_expense_inventory_anomalies(actor=actor, expense_request=updated)
    if decision == ExpenseTechnicalOpinion.Decision.REJECTED:
        roles = {ProjectMembership.Role.CONTRACTOR}
    else:
        roles = {ProjectMembership.Role.OWNER}
        if updated.pivot_review_required:
            roles.add(ProjectMembership.Role.PIVOT_REVIEWER)
    _notify_expense_roles(
        expense_request=updated, actor=actor, roles=roles,
        title="Nouvel avis technique sur une dépense",
        message=f"{updated.project.name} · {updated.purpose} : {opinion.get_decision_display()} · version {updated.status_version}.",
    )
    return opinion, updated


EXCEPTIONAL_PIVOT_CONFIRMATION = "JE CONFIRME L’INTERVENTION EXCEPTIONNELLE"


@transaction.atomic
def submit_expense_pivot_verification(
    *, actor, expense_request, decision, reason, expected_version,
    is_exceptional=False, confirmation="",
):
    locked = ExpenseRequest.objects.select_for_update().select_related("project").get(pk=expense_request.pk)
    if locked.status_version != expected_version:
        raise ValidationError("La demande a changé. Actualisez la page avant la vérification PIVOT.")
    if locked.status != ExpenseRequest.Status.VERIFIED:
        raise ValidationError("La vérification PIVOT exige un avis technique valide.")
    if not has_project_role(
        user=actor, project=locked.project, roles={ProjectMembership.Role.PIVOT_REVIEWER}
    ):
        raise PermissionDenied
    if decision not in ExpensePivotVerification.Decision.values or not reason.strip():
        raise ValidationError("La décision PIVOT et sa motivation sont obligatoires.")
    risk = evaluate_expense_risk(locked)
    issues = expense_dossier_inconsistencies(locked)
    if issues:
        raise ValidationError("Le dossier est incomplet ou incohérent : " + "; ".join(issues) + ".")
    if is_exceptional:
        if not actor.is_superuser:
            raise PermissionDenied
        if confirmation.strip() != EXCEPTIONAL_PIVOT_CONFIRMATION:
            raise ValidationError("La confirmation explicite de l’intervention exceptionnelle est incorrecte.")

    ExpensePivotVerification.objects.filter(request=locked, is_current=True).update(
        is_current=False, superseded_at=timezone.now()
    )
    verification = ExpensePivotVerification.objects.create(
        organization=locked.organization, request=locked, reviewer=actor,
        decision=decision, reason=reason.strip(),
        reviewed_status_version=locked.status_version,
        risk_score_snapshot=risk["score"], risk_reasons_snapshot=risk["reasons"],
        is_exceptional=is_exceptional,
        confirmation=confirmation.strip() if is_exceptional else "",
    )
    if decision == ExpensePivotVerification.Decision.REJECTED:
        updated = _rewind_expense_for_substantive_change(
            expense_request=locked, actor=actor,
            reason="Vérification PIVOT rejetée : retour aux preuves",
            supersede_opinion=False,
        )
    else:
        updated = locked
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor,
        action=("expense_request.pivot_exceptional_intervention" if is_exceptional else "expense_request.pivot_verification_submitted"),
        target_type="expense_pivot_verification", target_id=str(verification.pk),
        metadata={
            "request_id": str(locked.pk), "decision": decision,
            "reviewed_status_version": verification.reviewed_status_version,
            "risk_score": risk["score"], "risk_reasons": risk["reasons"],
            "exceptional_confirmation": bool(is_exceptional),
            "resulting_request_status": updated.status,
        },
    )
    _notify_expense_roles(
        expense_request=updated, actor=actor,
        roles={ProjectMembership.Role.OWNER, ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER},
        title="Décision de vérification PIVOT",
        message=f"{updated.project.name} · {updated.purpose} : {verification.get_decision_display()} · version {updated.status_version}.",
    )
    return verification, updated


@transaction.atomic
def decide_expense_by_owner(*, actor, expense_request, decision, reason, expected_version):
    locked = ExpenseRequest.objects.select_for_update().select_related("project").get(pk=expense_request.pk)
    if locked.status_version != expected_version:
        raise ValidationError("La demande a changé. Actualisez la page avant de décider.")
    if locked.status != ExpenseRequest.Status.VERIFIED:
        raise ValidationError("Seule une demande vérifiée peut recevoir la décision du propriétaire.")
    if not can_authorize_project_finance(user=actor, project=locked.project):
        raise PermissionDenied("Seul le propriétaire confirmé du chantier peut prendre cette décision.")
    if decision not in ExpenseOwnerDecision.Decision.values:
        raise ValidationError("Décision propriétaire invalide.")
    from apps.planning.services import inspection_requirement_is_satisfied
    if decision == ExpenseOwnerDecision.Decision.APPROVED and not inspection_requirement_is_satisfied(locked.milestone):
        raise ValidationError("Une inspection PIVOT Site Verified est imposée par la règle de risque de cette étape.")
    reason = reason.strip()
    if decision == ExpenseOwnerDecision.Decision.REJECTED and not reason:
        raise ValidationError("Le motif du refus est obligatoire.")

    risk = evaluate_expense_risk(locked)
    issues = expense_dossier_inconsistencies(locked)
    if issues:
        raise ValidationError("Le dossier est incomplet ou incohérent : " + "; ".join(issues) + ".")
    if (
        decision == ExpenseOwnerDecision.Decision.APPROVED
        and locked.inventory_anomalies.filter(status="open", action="block").exists()
    ):
        raise ValidationError(
            "L’autorisation est bloquée par une anomalie de consommation non résolue."
        )
    if risk["required"]:
        verification = locked.pivot_verifications.filter(is_current=True).first()
        if not verification or verification.decision != ExpensePivotVerification.Decision.APPROVED:
            raise ValidationError("La vérification PIVOT est obligatoire avant la décision du propriétaire.")
        if verification.reviewed_status_version != locked.status_version:
            raise ValidationError("La vérification PIVOT ne correspond plus à cette version du dossier.")

    previous_status = locked.status
    decided_version = locked.status_version
    locked.status = (
        ExpenseRequest.Status.AUTHORIZED
        if decision == ExpenseOwnerDecision.Decision.APPROVED
        else ExpenseRequest.Status.REJECTED
    )
    locked.status_version += 1
    locked.save(update_fields=("status", "status_version", "updated_at"))
    ExpenseRequestTransition.objects.create(
        request=locked, actor=actor, previous_status=previous_status,
        new_status=locked.status,
        reason=reason or "Autorisation explicite du propriétaire confirmé",
        status_version=locked.status_version,
    )
    owner_decision = ExpenseOwnerDecision.objects.create(
        organization=locked.organization, request=locked, owner=actor,
        decision=decision, reason=reason,
        decided_status_version=decided_version,
        resulting_status_version=locked.status_version,
    )
    AuditEvent.objects.create(
        organization=locked.organization, actor=actor,
        action="expense_request.owner_decision",
        target_type="expense_owner_decision", target_id=str(owner_decision.pk),
        metadata={
            "request_id": str(locked.pk), "decision": decision,
            "decided_status_version": decided_version,
            "resulting_status_version": locked.status_version,
            "reason": reason,
        },
    )
    recipients = User.objects.filter(
        project_memberships__project=locked.project,
        project_memberships__project_role__in={
            ProjectMembership.Role.CONTRACTOR,
            ProjectMembership.Role.ENGINEER,
            ProjectMembership.Role.PIVOT_REVIEWER,
        },
    ).exclude(pk=actor.pk).distinct()
    for recipient in recipients:
        create_notification(
            recipient=recipient, actor=actor, kind=Notification.Kind.FINANCE,
            title="Décision du propriétaire sur une demande de dépense",
            message=(
                f"{locked.project.name} · {locked.purpose} : "
                f"{owner_decision.get_decision_display()}."
                + (f" Motif : {reason}" if reason else "")
            ),
            target_url=f"{locked.project.get_absolute_url()}?tab=expenses",
            project=locked.project,
        )
    return owner_decision, locked


logger = logging.getLogger("pivot.payments")


def financial_totals(project):
    paid = project.payment_transactions.filter(status="success").aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal(0)
    withdrawn = project.withdrawals.filter(status="accounted").aggregate(v=Sum("amount"))[
        "v"
    ] or Decimal(0)
    return {
        "budget": project.budget_amount,
        "paid": paid,
        "available": paid - withdrawn,
        "remaining": max(project.budget_amount - paid, Decimal(0)),
        "withdrawn": withdrawn,
    }


def initiate_payment(*, actor, project, amount, operator, phone, idempotency_key, gateway=None):
    if not is_project_owner(user=actor, project=project):
        raise PermissionDenied
    if not can_authorize_project_finance(user=actor, project=project):
        raise ValidationError(
            "Le propriétaire du chantier doit confirmer son ownership avant tout paiement."
        )
    if not project_finance_is_unlocked(project):
        raise ValidationError(
            "Les finances restent verrouillées jusqu'à l'activation du chantier."
        )
    amount = Decimal(amount)
    if amount <= 0 or not phone or not operator:
        raise ValidationError("Paiement invalide")
    selected_gateway = gateway or configured_gateway()
    provider = getattr(selected_gateway, "provider", "custom")
    if not isinstance(provider, str):
        provider = "custom"
    close_stale_pending_for_project_user(
        actor=actor, project=project, gateway=selected_gateway
    )
    try:
        with transaction.atomic():
            existing = PaymentTransaction.objects.filter(idempotency_key=idempotency_key).first()
            if existing:
                logger.info("CLIENT PAYMENT idempotent-return transaction_id=%s status=%s", existing.pk, existing.status)
                return existing, False
            pending = (
                PaymentTransaction.objects.select_for_update()
                .filter(project=project, user=actor, status=PaymentTransaction.Status.PENDING)
                .first()
            )
            if pending:
                logger.warning(
                    "CLIENT PAYMENT blocked-by-pending transaction_id=%s project=%s user=%s",
                    pending.pk, project.pk, actor.pk,
                )
                return pending, False
            tx = PaymentTransaction.objects.create(
                organization=project.organization,
                project=project,
                user=actor,
                amount=amount,
                operator=operator,
                payer_phone=phone,
                idempotency_key=idempotency_key,
                provider=provider,
            )
            logger.info(
                "CLIENT PAYMENT created transaction_id=%s organization=%s project=%s user=%s amount=%s operator=%s provider=%s",
                tx.pk, project.organization_id, project.pk, actor.pk, amount, operator, provider,
            )
    except IntegrityError:
        # La contrainte conditionnelle protège aussi deux requêtes réellement simultanées.
        existing = PaymentTransaction.objects.filter(
            project=project, user=actor, status=PaymentTransaction.Status.PENDING
        ).first()
        if existing:
            return existing, False
        raise
    try:
        result = selected_gateway.collect(
            amount=amount, operator=operator, phone=phone, reference=str(tx.pk)
        )
        with transaction.atomic():
            locked_tx = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)
            if locked_tx.status == PaymentTransaction.Status.PENDING:
                locked_tx.status = result.status
                locked_tx.provider_reference = result.reference
                locked_tx.operator_reference = result.operator_reference
                locked_tx.raw_response_redacted = result.redacted or {}
                if result.status in {"success", "failed", "cancelled", "expired"}:
                    locked_tx.completed_at = timezone.now()
                locked_tx.save(
                    update_fields=(
                        "status",
                        "provider_reference",
                        "operator_reference",
                        "raw_response_redacted",
                        "completed_at",
                    )
                )
                logger.info(
                    "CLIENT PAYMENT provider-result transaction_id=%s provider_reference=%s status=%s",
                    locked_tx.pk, locked_tx.provider_reference or "<vide>", locked_tx.status,
                )
            tx = locked_tx
    except Exception as exc:
        logger.exception(
            "CLIENT PAYMENT provider-error transaction_id=%s error_type=%s",
            tx.pk, type(exc).__name__,
        )
        PaymentTransaction.objects.filter(
            pk=tx.pk, status=PaymentTransaction.Status.PENDING
        ).update(raw_response_redacted={"error": "provider_unavailable"})
        tx.refresh_from_db()
    for engineer in project_engineers(project).exclude(pk=actor.pk):
        create_notification(
            recipient=engineer,
            actor=actor,
            kind=Notification.Kind.FINANCE,
            title="Nouveau paiement sur le projet",
            message=f"{project.name} : {tx.get_status_display()}.",
            target_url=f"{project.get_absolute_url()}?tab=finance",
            project=project,
        )
    return tx, True


def _close_expense_after_success(*, tx, actor):
    if tx.status != PaymentTransaction.Status.SUCCESS or not tx.expense_request_id:
        return
    expense = ExpenseRequest.objects.select_for_update().get(pk=tx.expense_request_id)
    if expense.status != ExpenseRequest.Status.AUTHORIZED:
        return
    previous_status = expense.status
    expense.status = ExpenseRequest.Status.CLOSED
    expense.status_version += 1
    expense.save(update_fields=("status", "status_version", "updated_at"))
    ExpenseRequestTransition.objects.create(
        request=expense, actor=actor, previous_status=previous_status,
        new_status=expense.status, reason="Paiement MeSomb confirmé",
        status_version=expense.status_version,
    )
    AuditEvent.objects.create(
        organization=expense.organization, actor=actor,
        action="expense_request.payment_accounted", target_type="payment_transaction",
        target_id=str(tx.pk),
        metadata={
            "expense_request_id": str(expense.pk),
            "pivot_reference": tx.pivot_reference,
            "mesomb_reference": tx.provider_reference,
            "operator_reference": tx.operator_reference,
            "amount": str(tx.amount), "currency": tx.currency,
            "status_version": expense.status_version,
        },
    )
    _notify_expense_roles(
        expense_request=expense,
        actor=actor,
        roles={ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER},
        title="Paiement de dépense comptabilisé",
        message=(f"{expense.project.name} · {expense.purpose} : {tx.amount} {tx.currency} "
                 f"confirmés · version {expense.status_version}."),
    )


def initiate_expense_payment(
    *, actor, expense_request, operator, phone, idempotency_key, gateway=None,
):
    if (
        expense_request.status == ExpenseRequest.Status.AUTHORIZED
        and can_authorize_project_finance(user=actor, project=expense_request.project)
    ):
        from apps.inventory.services import detect_expense_inventory_anomalies
        findings = detect_expense_inventory_anomalies(actor=actor, expense_request=expense_request)
        blocking = [anomaly for anomaly in findings if anomaly.blocks_payment]
        if blocking:
            raise ValidationError(
                "Paiement bloqué par une anomalie de stock : "
                + ", ".join(anomaly.item.name for anomaly in blocking)
                + "."
            )
    selected_gateway = gateway or configured_gateway()
    provider = getattr(selected_gateway, "provider", "custom")
    if not isinstance(provider, str):
        provider = "custom"
    close_stale_pending_for_project_user(
        actor=actor, project=expense_request.project, gateway=selected_gateway
    )
    with transaction.atomic():
        expense = ExpenseRequest.objects.select_for_update().select_related("project").get(pk=expense_request.pk)
        if expense.status != ExpenseRequest.Status.AUTHORIZED:
            raise ValidationError("Cette demande de dépense n’est pas autorisée.")
        if not can_authorize_project_finance(user=actor, project=expense.project):
            raise PermissionDenied("Seul le propriétaire confirmé peut exécuter ce paiement.")
        if not project_finance_is_unlocked(expense.project):
            raise ValidationError("Les finances du chantier ne sont pas encore activées.")
        if not operator or not phone:
            raise ValidationError("L’opérateur et le téléphone du payeur sont obligatoires.")
        decision = expense.owner_decisions.filter(
            decision=ExpenseOwnerDecision.Decision.APPROVED,
            resulting_status_version=expense.status_version,
        ).first()
        if not decision or decision.owner_id != actor.pk:
            raise ValidationError("L’autorisation propriétaire ne correspond plus à cette version.")
        existing = PaymentTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing, False
        previous = expense.payment_transactions.filter(
            status__in={PaymentTransaction.Status.PENDING, PaymentTransaction.Status.SUCCESS}
        ).first()
        if previous:
            logger.warning(
                "EXPENSE PAYMENT blocked request=%s transaction=%s status=%s",
                expense.pk, previous.pk, previous.status,
            )
            return previous, False
        if PaymentTransaction.objects.filter(
            project=expense.project, user=actor, status=PaymentTransaction.Status.PENDING
        ).exists():
            raise ValidationError("Un autre paiement incertain est déjà en cours sur ce chantier.")
        tx = PaymentTransaction.objects.create(
            organization=expense.organization, project=expense.project, user=actor,
            expense_request=expense, owner_decision=decision,
            amount=expense.amount, currency=expense.currency,
            beneficiary_snapshot=expense.beneficiary,
            operator=operator, payer_phone=phone,
            idempotency_key=idempotency_key, provider=provider,
        )
        logger.info(
            "EXPENSE PAYMENT created transaction_id=%s pivot_reference=%s request=%s amount=%s currency=%s beneficiary=%s operator=%s payer=%s provider=%s",
            tx.pk, tx.pivot_reference, expense.pk, tx.amount, tx.currency,
            tx.beneficiary_snapshot, operator, str(phone)[-4:].rjust(len(str(phone)), "*"), provider,
        )
    try:
        result = selected_gateway.collect(
            amount=tx.amount, operator=operator, phone=phone, reference=tx.pivot_reference
        )
        with transaction.atomic():
            tx = PaymentTransaction.objects.select_for_update().select_related("user").get(pk=tx.pk)
            if tx.status == PaymentTransaction.Status.PENDING:
                tx.status = result.status
                tx.provider_reference = result.reference
                tx.operator_reference = result.operator_reference
                tx.raw_response_redacted = result.redacted or {}
                if tx.status in {"success", "failed", "cancelled", "expired"}:
                    tx.completed_at = timezone.now()
                tx.save(update_fields=(
                    "status", "provider_reference", "operator_reference",
                    "raw_response_redacted", "completed_at",
                ))
                _close_expense_after_success(tx=tx, actor=actor)
            logger.info(
                "EXPENSE PAYMENT result transaction_id=%s pivot_reference=%s mesomb_reference=%s operator_reference=%s status=%s",
                tx.pk, tx.pivot_reference, tx.provider_reference or "<vide>",
                tx.operator_reference or "<vide>", tx.status,
            )
    except Exception as exc:
        logger.exception(
            "EXPENSE PAYMENT uncertain transaction_id=%s pivot_reference=%s error_type=%s",
            tx.pk, tx.pivot_reference, type(exc).__name__,
        )
        PaymentTransaction.objects.filter(pk=tx.pk, status="pending").update(
            raw_response_redacted={"error": "provider_unavailable"}
        )
        tx.refresh_from_db()
    return tx, True


def reconcile_payment(*, actor, transaction_id, gateway=None):
    tx = PaymentTransaction.objects.select_related("project", "user").get(pk=transaction_id)
    if not can_monitor_project_finance(user=actor, project=tx.project):
        raise PermissionDenied
    if tx.status != PaymentTransaction.Status.PENDING:
        return tx, False
    selected_gateway = gateway or configured_gateway()
    reference = tx.provider_reference or tx.pivot_reference
    source = (
        "MESOMB"
        if tx.provider_reference and tx.provider_reference not in {str(tx.pk), tx.pivot_reference}
        else "EXTERNAL"
    )
    logger.info(
        "CLIENT PAYMENT reconciliation-start transaction_id=%s reference=%s source=%s",
        tx.pk, reference, source,
    )
    try:
        result = selected_gateway.query(reference=reference, source=source)
    except Exception as exc:
        logger.exception(
            "CLIENT PAYMENT reconciliation-error transaction_id=%s error_type=%s",
            tx.pk, type(exc).__name__,
        )
        PaymentTransaction.objects.filter(
            pk=tx.pk, status=PaymentTransaction.Status.PENDING
        ).update(raw_response_redacted={"error": "provider_unavailable"})
        tx.refresh_from_db()
        return tx, False
    with transaction.atomic():
        tx = (
            PaymentTransaction.objects.select_for_update()
            .select_related("project", "user")
            .get(pk=transaction_id)
        )
        previous_status = tx.status
        if previous_status != PaymentTransaction.Status.PENDING:
            return tx, False
        tx.status = result.status
        tx.provider_reference = result.reference or tx.provider_reference
        tx.operator_reference = result.operator_reference or tx.operator_reference
        tx.raw_response_redacted = result.redacted or {}
        if tx.status in {
            PaymentTransaction.Status.SUCCESS,
            PaymentTransaction.Status.FAILED,
            PaymentTransaction.Status.CANCELLED,
            PaymentTransaction.Status.EXPIRED,
        }:
            tx.completed_at = timezone.now()
        tx.save(
            update_fields=("status", "provider_reference", "operator_reference", "raw_response_redacted", "completed_at")
        )
        _close_expense_after_success(tx=tx, actor=tx.user)
        logger.info(
            "CLIENT PAYMENT reconciliation-result transaction_id=%s previous_status=%s new_status=%s provider_reference=%s",
            tx.pk, previous_status, tx.status, tx.provider_reference or "<vide>",
        )
    if tx.status != previous_status:
        AuditEvent.objects.create(
            organization=tx.organization,
            actor=actor,
            action="payment.reconciled",
            target_type="payment_transaction",
            target_id=str(tx.pk),
            metadata={"previous_status": previous_status, "new_status": tx.status},
        )
    return tx, tx.status != previous_status


@transaction.atomic
def expire_stale_payment(*, actor, transaction_id, reason, provider_checked=False):
    """Close an unverifiable pending payment while preserving its audit trail."""
    tx = PaymentTransaction.objects.select_for_update().get(pk=transaction_id)
    if tx.status != PaymentTransaction.Status.PENDING:
        return tx, False
    if (tx.provider_reference or tx.operator_reference) and not provider_checked:
        raise ValidationError(
            "Un paiement disposant d'une référence opérateur doit d'abord être rapproché."
        )
    previous_payload = dict(tx.raw_response_redacted or {})
    tx.status = PaymentTransaction.Status.EXPIRED
    tx.completed_at = timezone.now()
    tx.raw_response_redacted = {
        **previous_payload,
        "resolution": "expired_stale_without_provider_reference",
        "reason": reason,
    }
    tx.save(update_fields=("status", "completed_at", "raw_response_redacted"))
    AuditEvent.objects.create(
        organization=tx.organization,
        actor=actor,
        action="payment.expired_stale",
        target_type="payment_transaction",
        target_id=str(tx.pk),
        metadata={
            "previous_status": PaymentTransaction.Status.PENDING,
            "new_status": PaymentTransaction.Status.EXPIRED,
            "reason": reason,
        },
    )
    logger.warning(
        "CLIENT PAYMENT stale-expired transaction_id=%s project=%s requested_at=%s",
        tx.pk, tx.project_id, tx.requested_at.isoformat(),
    )
    return tx, True


def pending_payment_is_stale(payment):
    from datetime import timedelta

    return payment.requested_at <= timezone.now() - timedelta(
        minutes=settings.PAYMENT_PENDING_TTL_MINUTES
    )


def close_stale_pending_for_project_user(*, actor, project, gateway):
    """Reconcile once, then expire a pending payment past its maximum lifetime."""
    pending = PaymentTransaction.objects.filter(
        project=project,
        user=actor,
        status=PaymentTransaction.Status.PENDING,
    ).first()
    if not pending or not pending_payment_is_stale(pending):
        return pending
    provider_checked = False
    if pending.provider == "mesomb" and (pending.provider_reference or pending.operator_reference):
        pending, _ = reconcile_payment(
            actor=actor, transaction_id=pending.pk, gateway=gateway
        )
        provider_checked = True
    if pending.status == PaymentTransaction.Status.PENDING:
        pending, _ = expire_stale_payment(
            actor=actor,
            transaction_id=pending.pk,
            reason="Délai maximal de paiement en attente dépassé.",
            provider_checked=provider_checked,
        )
    return pending


@transaction.atomic
def decide_withdrawal(*, actor, withdrawal, status):
    if not actor.is_superuser and actor.role != User.Role.ADMIN:
        raise PermissionDenied
    if status not in {"accounted", "rejected"}:
        raise ValidationError("Décision invalide")
    if withdrawal.status != Withdrawal.Status.PENDING:
        raise ValidationError("Cette demande a déjà été traitée.")
    withdrawal.status = status
    withdrawal.decided_by = actor
    withdrawal.decided_at = timezone.now()
    withdrawal.save()
    AuditEvent.objects.create(
        organization=withdrawal.organization,
        actor=actor,
        action="withdrawal.decided",
        target_type="withdrawal",
        target_id=str(withdrawal.pk),
        metadata={"status": status},
    )
    if withdrawal.requested_by_id != actor.pk:
        create_notification(
            recipient=withdrawal.requested_by,
            actor=actor,
            kind=Notification.Kind.FINANCE,
            title="Demande de retrait examinée",
            message=f"{withdrawal.project.name} : {withdrawal.get_status_display()}.",
            target_url=f"{withdrawal.project.get_absolute_url()}?tab=finance",
            project=withdrawal.project,
        )


def request_withdrawal(*, actor, project, amount, reason):
    if not can_manage_project(actor=actor, project=project):
        raise PermissionDenied
    if not project_finance_is_unlocked(project):
        raise ValidationError(
            "Les demandes financières restent verrouillées jusqu'à l'activation du chantier."
        )
    amount = Decimal(amount)
    if amount <= 0 or amount > financial_totals(project)["available"]:
        raise ValidationError("Montant indisponible")
    return Withdrawal.objects.create(
        organization=project.organization,
        project=project,
        amount=amount,
        reason=reason,
        requested_by=actor,
    )
