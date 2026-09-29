import calendar

from django.db import migrations
from django.utils import timezone


def add_three_months(value):
    month_index = value.month - 1 + 3
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def backfill_active_organization_trials(apps, schema_editor):
    organization_model = apps.get_model("organizations", "Organization")
    user_model = apps.get_model("accounts", "User")
    plan_model = apps.get_model("subscriptions", "SubscriptionPlan")
    subscription_model = apps.get_model("subscriptions", "OrganizationSubscription")
    event_model = apps.get_model("subscriptions", "SubscriptionEvent")
    plan = plan_model.objects.filter(code="professional", is_active=True).first()
    if not plan:
        return
    snapshot = {
        "id": str(plan.pk),
        "code": plan.code,
        "name": plan.name,
        "monthly_price": str(plan.monthly_price),
        "yearly_price": str(plan.yearly_price),
        "currency": plan.currency,
        "max_active_projects": plan.max_active_projects,
        "max_internal_members": plan.max_internal_members,
        "storage_limit_mb": plan.storage_limit_mb,
        "advanced_reports_enabled": plan.advanced_reports_enabled,
        "ai_assistant_enabled": plan.ai_assistant_enabled,
        "features": plan.features,
    }
    started_at = timezone.now()
    organization_ids = user_model.objects.filter(
        role="engineer",
        is_active=True,
        organization__status="active",
    ).values_list("organization_id", flat=True)
    for organization in organization_model.objects.filter(pk__in=organization_ids).distinct():
        subscription, created = subscription_model.objects.get_or_create(
            organization=organization,
            defaults={
                "plan": plan,
                "status": "trial",
                "billing_cycle": "monthly",
                "trial_started_at": started_at,
                "trial_ends_at": add_three_months(started_at),
                "plan_snapshot": snapshot,
            },
        )
        if created:
            event_model.objects.create(
                subscription=subscription,
                event_type="subscription.trial_started",
                previous_status="",
                new_status="trial",
                plan_snapshot=snapshot,
                metadata={"trial_months": 3, "source": "e15_s2_backfill"},
            )


class Migration(migrations.Migration):
    dependencies = [("subscriptions", "0002_seed_initial_plans")]

    operations = [
        migrations.RunPython(
            backfill_active_organization_trials,
            migrations.RunPython.noop,
        )
    ]
