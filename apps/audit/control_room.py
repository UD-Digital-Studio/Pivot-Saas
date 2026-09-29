from datetime import datetime, time

from django.utils import timezone
from django.db.models import Sum

from apps.accounts.models import Invitation
from apps.accounts.models import User
from apps.finance.models import ExpenseRequest, ExpenseTechnicalOpinion
from apps.inventory.models import InventoryAnomaly, InventoryExpectedRange
from apps.planning.models import StageProgressVerification
from apps.projects.models import ProjectOnboarding, ProjectTermsVersion
from apps.subscriptions.models import OrganizationSubscription

from .models import PilotPricingHypothesis, PilotRecommendation, PilotReviewDecision


def _period_bounds(date_from=None, date_to=None):
    start = timezone.make_aware(datetime.combine(date_from, time.min)) if date_from else None
    end = timezone.make_aware(datetime.combine(date_to, time.max)) if date_to else None
    return start, end


def _within(queryset, field, start, end):
    if start:
        queryset = queryset.filter(**{f"{field}__gte": start})
    if end:
        queryset = queryset.filter(**{f"{field}__lte": end})
    return queryset


def adoption_metrics(*, date_from=None, date_to=None):
    """Single definition source for E22 adoption and conversion indicators."""
    start, end = _period_bounds(date_from, date_to)
    onboarding_cohort = _within(
        ProjectOnboarding.objects.select_related("project__ownership"),
        "created_at", start, end,
    )
    active_events = _within(
        ProjectOnboarding.objects.filter(status=ProjectOnboarding.Status.ACTIVE),
        "activated_at", start, end,
    )
    invitation_events = _within(Invitation.objects.all(), "created_at", start, end)
    accepted_events = _within(
        Invitation.objects.filter(accepted_at__isnull=False), "accepted_at", start, end
    )
    contractor_cohort = list(
        onboarding_cohort.filter(route=ProjectOnboarding.Route.CONTRACTOR_LED)
    )
    contractor_converted = sum(
        1
        for onboarding in contractor_cohort
        if hasattr(onboarding.project, "ownership") and onboarding.project.ownership.is_valid
    )
    contractor_total = len(contractor_cohort)
    return {
        "active_projects": active_events.count(),
        "routes": {
            route: onboarding_cohort.filter(route=route).count()
            for route, _ in ProjectOnboarding.Route.choices
        },
        "invitations_created": invitation_events.count(),
        "invitations_accepted": accepted_events.count(),
        "invitation_acceptance_rate": round(
            accepted_events.count() * 100 / invitation_events.count(), 1
        ) if invitation_events.count() else 0,
        "contractor_projects": contractor_total,
        "contractor_converted": contractor_converted,
        "contractor_conversion_rate": round(
            contractor_converted * 100 / contractor_total, 1
        ) if contractor_total else 0,
        "date_from": date_from,
        "date_to": date_to,
    }


def trust_value_metrics(*, date_from=None, date_to=None):
    """Confirmed trust/value metrics; pending declarations and reviews are excluded."""
    start, end = _period_bounds(date_from, date_to)
    active_onboardings = ProjectOnboarding.objects.filter(status=ProjectOnboarding.Status.ACTIVE)
    if end:
        active_onboardings = active_onboardings.filter(activated_at__lte=end)
    active_project_ids = active_onboardings.values_list("project_id", flat=True)
    confirmed_terms = ProjectTermsVersion.objects.filter(
        project_id__in=active_project_ids,
        is_current=True,
        authority_owner__isnull=False,
        actor_confirmations__project_role="owner",
        actor_confirmations__status="accepted",
    ).distinct()
    tracked = confirmed_terms.aggregate(total=Sum("budget_amount"))

    verified_expenses = ExpenseRequest.objects.filter(
        project_id__in=active_project_ids,
        status__in=(
            ExpenseRequest.Status.VERIFIED,
            ExpenseRequest.Status.AUTHORIZED,
            ExpenseRequest.Status.CLOSED,
        ),
        technical_opinions__is_current=True,
        technical_opinions__decision__in=(
            ExpenseTechnicalOpinion.Decision.APPROVED,
            ExpenseTechnicalOpinion.Decision.CONDITIONAL,
        ),
    )
    verified_expenses = _within(
        verified_expenses, "technical_opinions__created_at", start, end
    ).distinct()
    expense_total = verified_expenses.aggregate(total=Sum("amount"))

    verifications = _within(
        StageProgressVerification.objects.filter(stage__project_id__in=active_project_ids)
        .select_related("declaration"),
        "created_at", start, end,
    )
    delays = []
    for verification in verifications:
        if verification.declaration_id:
            completed_at = verification.signed_at or verification.created_at
            delays.append(max(0, (completed_at - verification.declaration.created_at).total_seconds()))

    anomalies = _within(
        InventoryAnomaly.objects.filter(project_id__in=active_project_ids),
        "detected_at", start, end,
    )
    return {
        "tracked_value": tracked["total"] or 0,
        "tracked_project_count": confirmed_terms.count(),
        "verified_expense_amount": expense_total["total"] or 0,
        "verified_expense_count": verified_expenses.count(),
        "verified_milestone_count": verifications.values("stage_id").distinct().count(),
        "verification_count": verifications.count(),
        "anomaly_count": anomalies.count(),
        "open_anomaly_count": anomalies.filter(status=InventoryAnomaly.Status.OPEN).count(),
        "resolved_anomaly_count": anomalies.filter(status=InventoryAnomaly.Status.RESOLVED).count(),
        "blocking_anomaly_count": anomalies.filter(
            status=InventoryAnomaly.Status.OPEN,
            action=InventoryExpectedRange.OutOfRangeAction.BLOCK,
        ).count(),
        "average_verification_delay_hours": round(sum(delays) / len(delays) / 3600, 1)
        if delays else None,
        "delay_sample_count": len(delays),
    }


def concierge_checklist(project):
    onboarding = getattr(project, "onboarding", None)
    follow_up = getattr(onboarding, "concierge_follow_up", None) if onboarding else None
    ownership = getattr(project, "ownership", None)
    items = (
        ("Budget", bool(project.budget_amount and project.budget_amount > 0)),
        ("Jalons", project.stages.exists()),
        ("Documents", project.documents.exists()),
        ("Invitations", project.actor_invitations.exists()),
        ("Formation", bool(follow_up and follow_up.training_completed)),
    )
    completed = sum(1 for _, done in items if done)
    return {
        "items": items,
        "completed": completed,
        "total": len(items),
        "percent": round(completed * 100 / len(items)),
        "owner": ownership.owner if ownership and ownership.is_valid else None,
        "follow_up": follow_up,
    }


def pilot_economy_metrics(*, date_from=None, date_to=None):
    start, end = _period_bounds(date_from, date_to)
    retention = {}
    for role in (User.Role.CLIENT, User.Role.CONTRACTOR):
        cohort = User.objects.filter(
            role=role, is_active=True,
            project_memberships__project__onboarding__status=ProjectOnboarding.Status.ACTIVE,
        ).distinct()
        if end:
            cohort = cohort.filter(date_joined__lte=end)
        retained = cohort.filter(last_login__isnull=False)
        if start:
            retained = retained.filter(last_login__gte=start)
        if end:
            retained = retained.filter(last_login__lte=end)
        total = cohort.count()
        count = retained.count()
        retention[role] = {
            "cohort": total, "retained": count,
            "rate": round(count * 100 / total, 1) if total else 0,
        }

    recommendations = _within(
        PilotRecommendation.objects.all(), "recorded_at", start, end
    )
    scores = list(recommendations.values_list("score", flat=True))
    promoters = sum(score >= 9 for score in scores)
    detractors = sum(score <= 6 for score in scores)
    nps = round((promoters - detractors) * 100 / len(scores), 1) if scores else None

    mrr = 0
    paid_subscriptions = OrganizationSubscription.objects.filter(
        status=OrganizationSubscription.Status.ACTIVE
    ).select_related("plan")
    for subscription in paid_subscriptions:
        snapshot = subscription.plan_snapshot or subscription.plan.snapshot()
        if subscription.billing_cycle == OrganizationSubscription.BillingCycle.YEARLY:
            mrr += int(snapshot.get("yearly_price", 0)) / 12
        else:
            mrr += int(snapshot.get("monthly_price", 0))

    hypotheses = list(PilotPricingHypothesis.objects.select_related("plan")[:10])
    return {
        "retention": retention,
        "recommendation_count": len(scores),
        "promoters": promoters,
        "detractors": detractors,
        "nps": nps,
        "mrr": round(mrr),
        "paid_organization_count": paid_subscriptions.count(),
        "pricing_hypotheses": hypotheses,
        "validated_hypothesis_count": sum(
            item.status == PilotPricingHypothesis.Status.VALIDATED for item in hypotheses
        ),
    }


def pilot_review_snapshot(*, horizon_days, as_of_date):
    """Build a PII-minimized 30/60/90-day snapshot from canonical E22 metrics."""
    if horizon_days not in PilotReviewDecision.Horizon.values:
        raise ValueError("L’horizon doit être de 30, 60 ou 90 jours.")
    date_from = as_of_date - timezone.timedelta(days=horizon_days - 1)
    adoption = adoption_metrics(date_from=date_from, date_to=as_of_date)
    trust = trust_value_metrics(date_from=date_from, date_to=as_of_date)
    economy = pilot_economy_metrics(date_from=date_from, date_to=as_of_date)
    start, end = _period_bounds(date_from, as_of_date)
    follow_ups = _within(
        ProjectOnboarding.objects.filter(concierge_follow_up__isnull=False),
        "concierge_follow_up__updated_at", start, end,
    )
    friction_count = follow_ups.exclude(concierge_follow_up__friction="").count()
    decision = PilotReviewDecision.objects.filter(
        horizon_days=horizon_days, as_of_date=as_of_date
    ).select_related("recorded_by").first()
    return {
        "horizon_days": horizon_days,
        "date_from": date_from,
        "date_to": as_of_date,
        "adoption": adoption,
        "trust": trust,
        "economy": economy,
        "cohorts": {
            "client": economy["retention"][User.Role.CLIENT],
            "contractor": economy["retention"][User.Role.CONTRACTOR],
            "routes": adoption["routes"],
        },
        "friction_count": friction_count,
        "decision": decision,
        "privacy_note": (
            "Données agrégées uniquement : aucun nom, e-mail, téléphone, commentaire libre "
            "ou identifiant utilisateur n’est inclus dans l’export."
        ),
    }
