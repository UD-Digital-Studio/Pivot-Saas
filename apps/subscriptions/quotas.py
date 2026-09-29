from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import Invitation, User
from apps.projects.models import Project

from .models import OrganizationSubscription

INTERNAL_ROLES = (
    User.Role.CONTRACTOR,
    User.Role.ENGINEER,
    User.Role.SITE_MANAGER,
    User.Role.ADMIN,
)
ACTIVE_PROJECT_STATUSES = (Project.Status.PENDING, Project.Status.ONGOING)


@dataclass(frozen=True)
class QuotaMetric:
    used: int
    limit: int | None
    percentage: int
    warning: bool
    reached: bool


def _metric(used, limit):
    if limit is None:
        return QuotaMetric(used, None, 0, False, False)
    percentage = min(round(used * 100 / limit), 100) if limit else 100
    return QuotaMetric(used, limit, percentage, percentage >= 80, used >= limit)


def _subscription(organization, *, lock=False):
    if not settings.SUBSCRIPTIONS_ENABLED:
        return None
    queryset = OrganizationSubscription.objects.select_related("plan")
    if lock:
        queryset = queryset.select_for_update()
    return queryset.filter(organization=organization).first()


def _limit(subscription, name):
    if not subscription:
        return None
    snapshot = subscription.plan_snapshot or {}
    value = snapshot.get(name, getattr(subscription.plan, name))
    return int(value) if value is not None else None


def quota_usage(organization):
    subscription = _subscription(organization)
    project_count = Project.objects.filter(
        organization=organization, status__in=ACTIVE_PROJECT_STATUSES
    ).count()
    member_count = User.objects.filter(
        organization=organization, is_active=True, role__in=INTERNAL_ROLES
    ).count()
    reservations = Invitation.objects.filter(
        organization=organization, role__in=INTERNAL_ROLES,
        accepted_at__isnull=True, canceled_at__isnull=True,
        expires_at__gt=timezone.now(),
    ).count()
    return {
        "plan": subscription.plan if subscription else None,
        "projects": _metric(project_count, _limit(subscription, "max_active_projects")),
        "members": _metric(member_count + reservations, _limit(subscription, "max_internal_members")),
        "active_members": member_count,
        "reserved_members": reservations,
    }


def ensure_project_capacity(organization):
    subscription = _subscription(organization, lock=True)
    limit = _limit(subscription, "max_active_projects")
    used = Project.objects.filter(
        organization=organization, status__in=ACTIVE_PROJECT_STATUSES
    ).count()
    if limit is not None and used >= limit:
        raise ValidationError(
            f"Limite de {limit} projets actifs atteinte. Terminez un projet ou choisissez un forfait supérieur."
        )


def ensure_internal_member_capacity(organization, role, *, exclude_user=None, exclude_invitation=None):
    if role not in INTERNAL_ROLES:
        return
    subscription = _subscription(organization, lock=True)
    limit = _limit(subscription, "max_internal_members")
    if limit is None:
        return
    users = User.objects.filter(organization=organization, is_active=True, role__in=INTERNAL_ROLES)
    invitations = Invitation.objects.filter(
        organization=organization, role__in=INTERNAL_ROLES,
        accepted_at__isnull=True, canceled_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    if exclude_user:
        users = users.exclude(pk=exclude_user.pk)
    if exclude_invitation:
        invitations = invitations.exclude(pk=exclude_invitation.pk)
    if users.count() + invitations.count() + 1 > limit:
        raise ValidationError(
            f"Limite de {limit} membres internes atteinte. Désactivez un membre, annulez une invitation ou choisissez un forfait supérieur."
        )


def subscription_feature_enabled(organization, feature):
    subscription = _subscription(organization)
    if not subscription:
        return True
    snapshot = subscription.plan_snapshot or {}
    return bool(snapshot.get(feature, getattr(subscription.plan, feature, False)))
