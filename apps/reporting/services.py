from django.utils.translation import gettext_lazy as _
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.finance.services import financial_totals
from apps.finance.models import ExpenseOwnerDecision, PaymentTransaction
from apps.collaboration.services import can_access_evidence
from apps.planning.models import StageVerificationReport


def parse_period(date_from="", date_to=""):
    try:
        start = date.fromisoformat(date_from) if date_from else None
        end = date.fromisoformat(date_to) if date_to else None
    except ValueError as error:
        raise ValidationError(_("Période invalide")) from error
    if start and end and end < start:
        raise ValidationError(_("La fin précède le début"))
    return start, end


def project_report_projection(*, project, date_from=None, date_to=None):
    def period(queryset, field):
        if date_from:
            queryset = queryset.filter(**{f"{field}__date__gte": date_from})
        if date_to:
            queryset = queryset.filter(**{f"{field}__date__lte": date_to})
        return queryset

    stages = project.stages.all()
    stock = project.stock_items.all()
    stage_count = stages.count()
    completed_stage_count = stages.filter(status="complete").count()
    declared_values = [stage.declared_progress_percent for stage in stages if stage.declared_progress_percent is not None]
    verified_values = [stage.verified_progress_percent for stage in stages if stage.verified_progress_percent is not None]
    declared_stage_progress = round(sum(declared_values) / len(declared_values)) if declared_values else None
    verified_stage_progress = round(sum(verified_values) / len(verified_values)) if verified_values else None
    stock_value = sum((item.total_price for item in stock), Decimal("0"))

    expense_requests = period(project.expense_requests.select_related("author", "milestone"), "created_at")
    expense_authorizations = period(
        ExpenseOwnerDecision.objects.filter(
            request__project=project, decision=ExpenseOwnerDecision.Decision.APPROVED,
        ).select_related("request", "owner"), "created_at",
    )
    payment_attempts = period(
        project.payment_transactions.filter(expense_request__isnull=False).select_related(
            "expense_request", "owner_decision", "user"
        ), "requested_at",
    )
    accounted_payments = period(
        project.payment_transactions.filter(
            expense_request__isnull=False, status=PaymentTransaction.Status.SUCCESS,
        ).select_related("expense_request", "owner_decision", "user"), "completed_at",
    )

    return {
        "project": project,
        "totals": financial_totals(project),
        "stages": stages,
        "stock": stock,
        "payments": period(project.payment_transactions.select_related("user"), "requested_at"),
        "expense_requests": expense_requests,
        "expense_authorizations": expense_authorizations,
        "payment_attempts": payment_attempts,
        "accounted_payments": accounted_payments,
        "withdrawals": period(project.withdrawals.select_related("requested_by"), "requested_at"),
        "comments": period(
            project.comments.filter(is_deleted=False).select_related("author"), "created_at"
        ),
        "evidence_records": period(
            project.evidence_records.select_related("author", "stage", "previous_version"),
            "captured_at",
        ),
        "date_from": date_from,
        "date_to": date_to,
        "generated_at": timezone.localtime(),
        "stage_count": stage_count,
        "completed_stage_count": completed_stage_count,
        "stage_progress": verified_stage_progress or 0,
        "declared_stage_progress": declared_stage_progress,
        "verified_stage_progress": verified_stage_progress,
        "stock_value": stock_value,
    }


def stage_verification_report_projection(*, actor, stage):
    technical = stage.latest_verified_progress
    if not technical or not technical.declaration_id or not technical.digital_verification_id:
        raise ValidationError(_("Les niveaux Digital Verified et Technically Verified sont requis."))

    site = technical.site_verifications.select_related("visit", "inspector").first()
    candidates = []
    for evidence in (technical.declaration.evidence, technical.evidence):
        if evidence and evidence.pk not in {item.pk for item in candidates}:
            candidates.append(evidence)
    if site:
        for evidence in site.evidence.select_related("author"):
            if evidence.pk not in {item.pk for item in candidates}:
                candidates.append(evidence)

    proofs = [evidence for evidence in candidates if can_access_evidence(
        actor=actor, evidence=evidence, action="export"
    )]
    report, report_created = StageVerificationReport.objects.get_or_create(
        technical_verification=technical,
        defaults={"organization": stage.organization, "generated_by": actor},
    )
    reservations = list(technical.reservations)
    if site:
        reservations.extend(site.reservations)
    return {
        "report": report, "project": stage.project, "stage": stage,
        "declaration": technical.declaration, "digital": technical.digital_verification,
        "technical": technical, "site": site, "proofs": proofs,
        "reservations": reservations, "generated_at": timezone.localtime(),
    }
