import calendar
import logging
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import OrganizationSubscription, SubscriptionEvent, SubscriptionNoticeDelivery, SubscriptionPayment, SubscriptionPlan


logger = logging.getLogger("pivot.payments")


def add_calendar_months(value: datetime, months: int) -> datetime:
    """Add calendar months while keeping the time and clamping the day when needed."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


@transaction.atomic
def start_organization_trial(*, organization, actor=None, activated_at=None):
    existing = OrganizationSubscription.objects.select_for_update().filter(
        organization=organization
    ).first()
    if existing:
        return existing, False

    plan_code = settings.SUBSCRIPTION_TRIAL_PLAN_CODE
    try:
        plan = SubscriptionPlan.objects.get(code=plan_code, is_active=True)
    except SubscriptionPlan.DoesNotExist as exc:
        raise ValidationError("Le forfait d’essai configuré est indisponible.") from exc

    started_at = activated_at or timezone.now()
    subscription = OrganizationSubscription(
        organization=organization,
        plan=plan,
        status=OrganizationSubscription.Status.TRIAL,
        billing_cycle=OrganizationSubscription.BillingCycle.MONTHLY,
        trial_started_at=started_at,
        trial_ends_at=add_calendar_months(started_at, settings.SUBSCRIPTION_TRIAL_MONTHS),
        plan_snapshot=plan.snapshot(),
    )
    subscription.full_clean()
    subscription.save()
    SubscriptionEvent.objects.create(
        subscription=subscription,
        actor=actor,
        event_type="subscription.trial_started",
        previous_status="",
        new_status=OrganizationSubscription.Status.TRIAL,
        plan_snapshot=subscription.plan_snapshot,
        metadata={"trial_months": settings.SUBSCRIPTION_TRIAL_MONTHS},
    )
    return subscription, True


def _payment_status(result):
    provider_status = str((result.redacted or {}).get("status", "")).upper()
    if provider_status in {"REJECTED", "DECLINED", "DENIED"}:
        return SubscriptionPayment.Status.REFUSED
    return result.status if result.status in SubscriptionPayment.Status.values else SubscriptionPayment.Status.PENDING


def payment_action(subscription, plan):
    if subscription.status == OrganizationSubscription.Status.ACTIVE:
        if plan.monthly_price > subscription.plan.monthly_price:
            return SubscriptionPayment.Action.UPGRADE
        if plan.monthly_price < subscription.plan.monthly_price:
            return SubscriptionPayment.Action.DOWNGRADE
    return SubscriptionPayment.Action.RENEWAL


@transaction.atomic
def _confirm_subscription_payment(payment):
    payment = SubscriptionPayment.objects.select_for_update().select_related("subscription", "plan").get(pk=payment.pk)
    if payment.status != SubscriptionPayment.Status.SUCCESS:
        return payment
    if not payment.receipt_reference:
        payment.receipt_reference = f"PIVOT-{timezone.now():%Y}-{payment.pk.hex.upper()}"
        payment.save(update_fields=("receipt_reference", "updated_at"))
    subscription = OrganizationSubscription.objects.select_for_update().get(pk=payment.subscription_id)
    now = timezone.now()
    start = subscription.current_period_ends_at if subscription.current_period_ends_at and subscription.current_period_ends_at > now else now
    months = 12 if payment.billing_cycle == OrganizationSubscription.BillingCycle.YEARLY else 1
    previous_status = subscription.status
    if payment.action == SubscriptionPayment.Action.DOWNGRADE and subscription.current_period_ends_at and subscription.current_period_ends_at > now:
        subscription.pending_plan = payment.plan
        subscription.pending_billing_cycle = payment.billing_cycle
        subscription.pending_effective_at = subscription.current_period_ends_at
        subscription.pending_period_ends_at = add_calendar_months(subscription.current_period_ends_at, months)
    else:
        subscription.plan = payment.plan
        subscription.plan_snapshot = payment.plan_snapshot
        subscription.billing_cycle = payment.billing_cycle
        subscription.status = OrganizationSubscription.Status.ACTIVE
        subscription.current_period_started_at = now if payment.action == SubscriptionPayment.Action.UPGRADE else start
        subscription.current_period_ends_at = add_calendar_months(start, months)
    subscription.save()
    SubscriptionEvent.objects.create(
        subscription=subscription, actor=payment.requested_by,
        event_type="subscription.payment_confirmed", previous_status=previous_status,
        new_status=subscription.status, plan_snapshot=payment.plan_snapshot,
        metadata={"payment_id": str(payment.pk), "billing_cycle": payment.billing_cycle, "action": payment.action, "effective_at": subscription.pending_effective_at.isoformat() if subscription.pending_effective_at else now.isoformat()},
    )
    return payment


def initiate_subscription_payment(*, actor, plan, billing_cycle, operator, phone, gateway=None):
    from apps.accounts.models import User
    from apps.finance.gateways import configured_gateway

    if actor.organization_id is None or actor.role not in {User.Role.ENGINEER, User.Role.ADMIN}:
        raise ValidationError("Vous ne pouvez pas payer l’abonnement de cette organisation.")
    if billing_cycle not in OrganizationSubscription.BillingCycle.values or not plan.is_active:
        raise ValidationError("Forfait ou périodicité invalide.")
    subscription = OrganizationSubscription.objects.get(organization=actor.organization)
    amount = plan.yearly_price if billing_cycle == OrganizationSubscription.BillingCycle.YEARLY else plan.monthly_price
    if amount <= 0:
        raise ValidationError("Ce forfait est disponible uniquement sur devis et ne peut pas être payé directement.")
    selected_gateway = gateway or configured_gateway()
    try:
        with transaction.atomic():
            existing = SubscriptionPayment.objects.select_for_update().filter(
                organization=actor.organization,
                status__in=(SubscriptionPayment.Status.INITIATED, SubscriptionPayment.Status.PENDING),
            ).first()
            if existing:
                return existing, False
            payment = SubscriptionPayment.objects.create(
                organization=actor.organization, subscription=subscription, plan=plan,
                requested_by=actor, billing_cycle=billing_cycle, amount=amount,
                currency=plan.currency, operator=operator, payer_phone=phone,
                provider=getattr(selected_gateway, "provider", "custom"), plan_snapshot=plan.snapshot(),
                action=payment_action(subscription, plan),
            )
            payment.status = SubscriptionPayment.Status.PENDING
            payment.save(update_fields=("status", "updated_at"))
            logger.info(
                "PIVOT PAYMENT created id=%s organization=%s plan=%s cycle=%s amount=%s operator=%s",
                payment.pk, actor.organization_id, plan.code, billing_cycle, amount, operator,
            )
    except IntegrityError:
        return SubscriptionPayment.objects.get(
            organization=actor.organization,
            status__in=(SubscriptionPayment.Status.INITIATED, SubscriptionPayment.Status.PENDING),
        ), False
    try:
        result = selected_gateway.collect(amount=amount, operator=operator, phone=phone, reference=str(payment.pk))
        if result.status == "pending" and result.reference:
            result = selected_gateway.query(reference=result.reference, source="MESOMB")
        with transaction.atomic():
            payment = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
            payment.status = _payment_status(result)
            payment.provider_reference = result.reference or ""
            payment.response_summary = result.redacted or {}
            if payment.status not in {SubscriptionPayment.Status.INITIATED, SubscriptionPayment.Status.PENDING}:
                payment.completed_at = timezone.now()
            payment.save()
    except Exception as exc:
        logger.exception(
            "MESOMB COLLECT error payment_id=%s error_type=%s",
            payment.pk, type(exc).__name__,
        )
        definitive_configuration_error = type(exc).__name__ in {
            "ServiceNotFoundException", "AuthenticationException", "PermissionDeniedException",
            "InvalidClientRequestException",
        }
        payment.response_summary = {
            "error": "provider_configuration_invalid"
            if definitive_configuration_error
            else "provider_unavailable",
            "error_type": type(exc).__name__,
        }
        if definitive_configuration_error:
            payment.status = SubscriptionPayment.Status.FAILED
            payment.completed_at = timezone.now()
            payment.save(update_fields=("status", "response_summary", "completed_at", "updated_at"))
        else:
            payment.save(update_fields=("response_summary", "updated_at"))
    if payment.status == SubscriptionPayment.Status.SUCCESS:
        payment = _confirm_subscription_payment(payment)
    notify_subscription_payment_outcome(payment)
    return payment, True


@transaction.atomic
def process_subscription_deadlines(*, now=None):
    now = now or timezone.now()
    changed = 0
    for subscription in OrganizationSubscription.objects.select_for_update().select_related("pending_plan", "plan"):
        previous_status = subscription.status
        event_type = ""
        if subscription.pending_plan_id and subscription.pending_effective_at and subscription.pending_effective_at <= now:
            subscription.plan = subscription.pending_plan
            subscription.plan_snapshot = subscription.pending_plan.snapshot()
            subscription.billing_cycle = subscription.pending_billing_cycle
            subscription.current_period_started_at = subscription.pending_effective_at
            subscription.current_period_ends_at = subscription.pending_period_ends_at
            subscription.pending_plan = None
            subscription.pending_billing_cycle = ""
            subscription.pending_effective_at = None
            subscription.pending_period_ends_at = None
            subscription.status = OrganizationSubscription.Status.ACTIVE
            event_type = "subscription.scheduled_change_applied"
        elif subscription.status == OrganizationSubscription.Status.TRIAL and subscription.trial_ends_at and subscription.trial_ends_at <= now:
            subscription.status = OrganizationSubscription.Status.GRACE
            subscription.grace_ends_at = now + timezone.timedelta(
                days=getattr(settings, "SUBSCRIPTION_GRACE_DAYS", 7)
            )
            event_type = "subscription.trial_grace_started"
        elif subscription.status == OrganizationSubscription.Status.ACTIVE and subscription.current_period_ends_at and subscription.current_period_ends_at <= now:
            grace_days = getattr(settings, "SUBSCRIPTION_GRACE_DAYS", 7)
            subscription.status = OrganizationSubscription.Status.GRACE
            subscription.grace_ends_at = now + timezone.timedelta(days=grace_days)
            event_type = "subscription.grace_started"
        elif subscription.status == OrganizationSubscription.Status.GRACE and subscription.grace_ends_at and subscription.grace_ends_at <= now:
            subscription.status = OrganizationSubscription.Status.READ_ONLY
            event_type = "subscription.grace_expired"
        if event_type:
            subscription.save()
            SubscriptionEvent.objects.create(
                subscription=subscription, event_type=event_type,
                previous_status=previous_status, new_status=subscription.status,
                plan_snapshot=subscription.plan_snapshot,
                metadata={"processed_at": now.isoformat()},
            )
            changed += 1
    return changed


def reconcile_subscription_payment(*, actor, payment, gateway=None):
    from apps.finance.gateways import configured_gateway

    if actor.organization_id != payment.organization_id and not actor.is_superuser:
        raise ValidationError("Paiement inaccessible.")
    if payment.status != SubscriptionPayment.Status.PENDING:
        return payment, False
    selected_gateway = gateway or configured_gateway()
    try:
        result = selected_gateway.query(reference=payment.provider_reference or str(payment.pk), source="MESOMB" if payment.provider_reference else "EXTERNAL")
    except Exception as exc:
        logger.exception(
            "MESOMB QUERY error payment_id=%s provider_reference=%s error_type=%s",
            payment.pk, payment.provider_reference or "<external-reference>", type(exc).__name__,
        )
        if type(exc).__name__ in {"ServiceNotFoundException", "AuthenticationException", "PermissionDeniedException", "InvalidClientRequestException"}:
            payment.status = SubscriptionPayment.Status.FAILED
            payment.response_summary = {
                "error": "provider_configuration_invalid",
                "error_type": type(exc).__name__,
            }
            payment.completed_at = timezone.now()
            payment.save(update_fields=("status", "response_summary", "completed_at", "updated_at"))
            notify_subscription_payment_outcome(payment)
            return payment, True
        return payment, False
    with transaction.atomic():
        payment = SubscriptionPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != SubscriptionPayment.Status.PENDING:
            return payment, False
        payment.status = _payment_status(result)
        payment.provider_reference = result.reference or payment.provider_reference
        payment.response_summary = result.redacted or {}
        if payment.status != SubscriptionPayment.Status.PENDING:
            payment.completed_at = timezone.now()
        payment.save()
    if payment.status == SubscriptionPayment.Status.SUCCESS:
        payment = _confirm_subscription_payment(payment)
    notify_subscription_payment_outcome(payment)
    return payment, True


def process_uncertain_subscription_payments(*, now=None, gateway=None):
    now = now or timezone.now()
    minimum_age = getattr(settings, "SUBSCRIPTION_PAYMENT_RECHECK_MINUTES", 2)
    threshold = now - timezone.timedelta(minutes=minimum_age)
    processed = 0
    payments = SubscriptionPayment.objects.filter(
        status=SubscriptionPayment.Status.PENDING, updated_at__lte=threshold
    ).select_related("requested_by")
    for payment in payments:
        _, checked = reconcile_subscription_payment(
            actor=payment.requested_by, payment=payment, gateway=gateway
        )
        processed += int(checked)
    return processed


def _subscription_recipients(subscription):
    from apps.accounts.models import User

    return User.objects.filter(
        organization=subscription.organization, is_active=True,
        role__in=(User.Role.ENGINEER, User.Role.ADMIN),
    )


def _deliver_subscription_notice(*, subscription, recipient, milestone, title, message, date=None):
    from django.templatetags.static import static
    from django.urls import reverse
    from apps.accounts.models import Notification
    from apps.accounts.services import create_notification, send_transactional_email

    billing_path = reverse("subscriptions:pricing")
    action_url = f"{settings.APP_BASE_URL}{billing_path}"
    _, app_created = SubscriptionNoticeDelivery.objects.get_or_create(
        subscription=subscription, recipient=recipient, milestone=milestone,
        channel=SubscriptionNoticeDelivery.Channel.IN_APP,
    )
    if app_created:
        create_notification(
            recipient=recipient, kind=Notification.Kind.FINANCE, title=title,
            message=message, target_url=billing_path,
        )
    email_delivery = None
    email_created = False
    if recipient.email:
        email_delivery, email_created = SubscriptionNoticeDelivery.objects.get_or_create(
            subscription=subscription, recipient=recipient, milestone=milestone,
            channel=SubscriptionNoticeDelivery.Channel.EMAIL,
        )
    if recipient.email and email_created:
        try:
            sent = send_transactional_email(
                subject=f"PIVOT — {title}", recipient=recipient.email,
                text_template="emails/subscription_notice.txt",
                html_template="emails/subscription_notice.html",
                context={
                    "user": recipient, "subscription": subscription, "title": title,
                    "message": message, "milestone": milestone, "deadline": date,
                    "action_url": action_url,
                    "logo_url": f"{settings.APP_BASE_URL}{static('images/Logo.png')}",
                },
            )
            if not sent:
                email_delivery.delete()
        except Exception:
            email_delivery.delete()


def process_subscription_notices(*, now=None):
    now = now or timezone.now()
    delivered = 0
    configured_days = tuple(getattr(settings, "SUBSCRIPTION_NOTICE_DAYS", (7, 3, 1)))
    for subscription in OrganizationSubscription.objects.select_related("organization", "plan"):
        deadline = subscription.trial_ends_at if subscription.status in {OrganizationSubscription.Status.TRIAL, OrganizationSubscription.Status.EXPIRED} and not subscription.current_period_ends_at else subscription.current_period_ends_at
        milestone = None
        title = ""
        message = ""
        if subscription.status == OrganizationSubscription.Status.GRACE and subscription.grace_ends_at:
            days = (subscription.grace_ends_at.date() - now.date()).days
            if days <= 0:
                milestone, title = "grace_end", "Fin de la période de grâce"
                message = f"Le forfait {subscription.plan.name} arrive en fin de grâce. L’organisation passera en lecture seule."
        elif deadline:
            days = (deadline.date() - now.date()).days
            if days in configured_days:
                milestone, title = f"due_{days}", f"Abonnement : échéance dans {days} jour(s)"
                message = f"Le forfait {subscription.plan.name} arrive à échéance le {deadline:%d/%m/%Y}. Renouvelez-le pour éviter les restrictions."
            elif days <= 0:
                milestone, title = "due_0", "Abonnement arrivé à échéance"
                message = f"Le forfait {subscription.plan.name} est arrivé à échéance. Consultez la facturation et les conséquences applicables."
        if not milestone:
            continue
        for recipient in _subscription_recipients(subscription):
            before = SubscriptionNoticeDelivery.objects.filter(subscription=subscription, recipient=recipient, milestone=milestone).count()
            _deliver_subscription_notice(subscription=subscription, recipient=recipient, milestone=milestone, title=title, message=message, date=deadline or subscription.grace_ends_at)
            delivered += SubscriptionNoticeDelivery.objects.filter(subscription=subscription, recipient=recipient, milestone=milestone).count() - before
    return delivered


def notify_subscription_payment_outcome(payment):
    if payment.status in {SubscriptionPayment.Status.INITIATED, SubscriptionPayment.Status.PENDING}:
        return
    milestone = f"pay_{str(payment.pk)[:8]}_{payment.status}"
    title = f"Paiement d’abonnement {payment.get_status_display().lower()}"
    message = f"Forfait {payment.plan.name} : {payment.amount} {payment.currency}."
    for recipient in _subscription_recipients(payment.subscription):
        _deliver_subscription_notice(subscription=payment.subscription, recipient=recipient, milestone=milestone, title=title, message=message)


@transaction.atomic
def correct_subscription_period(*, actor, subscription, starts_at, ends_at, reason):
    if not actor.is_superuser:
        raise ValidationError("Seul un super-administrateur peut corriger une période.")
    if not reason.strip() or ends_at <= starts_at:
        raise ValidationError("La période et le motif de correction sont obligatoires.")
    subscription = OrganizationSubscription.objects.select_for_update().get(pk=subscription.pk)
    previous = {
        "started_at": subscription.current_period_started_at.isoformat() if subscription.current_period_started_at else None,
        "ends_at": subscription.current_period_ends_at.isoformat() if subscription.current_period_ends_at else None,
    }
    subscription.current_period_started_at = starts_at
    subscription.current_period_ends_at = ends_at
    subscription.save(update_fields=("current_period_started_at", "current_period_ends_at", "updated_at"))
    SubscriptionEvent.objects.create(
        subscription=subscription, actor=actor, event_type="subscription.period_corrected",
        previous_status=subscription.status, new_status=subscription.status,
        plan_snapshot=subscription.plan_snapshot,
        metadata={"previous": previous, "new": {"started_at": starts_at.isoformat(), "ends_at": ends_at.isoformat()}, "reason": reason.strip()},
    )
    return subscription
