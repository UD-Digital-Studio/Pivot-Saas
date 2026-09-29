from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db.models import Sum

from apps.finance.models import ExpenseRequest, ExpenseTechnicalOpinion
from apps.inventory.models import InventoryAnomaly, InventoryExpectedRange
from apps.planning.models import StageProgressVerification

from .access import can_monitor_project_finance


CONTROLLED_EXPENSE_STATUSES = (
    ExpenseRequest.Status.VERIFIED,
    ExpenseRequest.Status.AUTHORIZED,
    ExpenseRequest.Status.CLOSED,
)


def controlled_value_indicators(*, actor, project):
    """Return permission-aware aggregates derived only from auditable records."""
    if not actor.is_superuser and not project.memberships.filter(user=actor).exists():
        raise PermissionDenied

    verifications = StageProgressVerification.objects.filter(
        organization=project.organization, stage__project=project
    ).select_related("declaration")
    verified_stage_count = verifications.values("stage_id").distinct().count()
    total_stage_count = project.stages.count()

    delays = []
    for verification in verifications:
        if verification.declaration_id:
            completed_at = verification.signed_at or verification.created_at
            delay = completed_at - verification.declaration.created_at
            delays.append(max(0, delay.total_seconds()))

    average_delay_hours = None
    maximum_delay_hours = None
    if delays:
        average_delay_hours = round(sum(delays) / len(delays) / 3600, 1)
        maximum_delay_hours = round(max(delays) / 3600, 1)

    result = {
        "verified_stage_count": verified_stage_count,
        "total_stage_count": total_stage_count,
        "verification_delay_count": len(delays),
        "average_verification_delay_hours": average_delay_hours,
        "maximum_verification_delay_hours": maximum_delay_hours,
        "can_view_financial_value": False,
        "verified_expense_count": None,
        "verified_expense_amount": None,
        "currency": "XAF",
        "anomaly_count": None,
        "open_anomaly_count": None,
        "resolved_anomaly_count": None,
        "blocking_anomaly_count": None,
    }

    if not can_monitor_project_finance(user=actor, project=project):
        return result

    verified_expenses = ExpenseRequest.objects.filter(
        organization=project.organization,
        project=project,
        status__in=CONTROLLED_EXPENSE_STATUSES,
        technical_opinions__is_current=True,
        technical_opinions__decision__in=(
            ExpenseTechnicalOpinion.Decision.APPROVED,
            ExpenseTechnicalOpinion.Decision.CONDITIONAL,
        ),
    ).distinct()
    expense_aggregate = verified_expenses.aggregate(total=Sum("amount"))
    anomalies = InventoryAnomaly.objects.filter(
        organization=project.organization, project=project
    )
    result.update(
        {
            "can_view_financial_value": True,
            "verified_expense_count": verified_expenses.count(),
            "verified_expense_amount": expense_aggregate["total"] or Decimal("0"),
            "anomaly_count": anomalies.count(),
            "open_anomaly_count": anomalies.filter(status=InventoryAnomaly.Status.OPEN).count(),
            "resolved_anomaly_count": anomalies.filter(status=InventoryAnomaly.Status.RESOLVED).count(),
            "blocking_anomaly_count": anomalies.filter(
                status=InventoryAnomaly.Status.OPEN,
                action=InventoryExpectedRange.OutOfRangeAction.BLOCK,
            ).count(),
        }
    )
    return result
