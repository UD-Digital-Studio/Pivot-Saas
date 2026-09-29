from collections.abc import Iterable

from django.db.models import QuerySet

from apps.accounts.models import User

from .models import Project, ProjectMembership, ProjectOwnership


PROJECT_MANAGEMENT_ROLES = frozenset(
    {ProjectMembership.Role.ENGINEER}
)
PROJECT_TECHNICAL_ROLES = frozenset(
    {ProjectMembership.Role.ENGINEER, ProjectMembership.Role.PIVOT_REVIEWER}
)
PROJECT_FINANCE_MONITOR_ROLES = frozenset(
    {
        ProjectMembership.Role.OWNER,
        ProjectMembership.Role.ENGINEER,
        ProjectMembership.Role.PIVOT_REVIEWER,
    }
)


def has_project_role(*, user: User, project: Project, roles: Iterable[str]) -> bool:
    """Return the contextual role explicitly granted for this project."""
    if user.is_superuser:
        return True
    if not user.is_authenticated:
        return False
    return ProjectMembership.objects.filter(
        organization_id=project.organization_id,
        project_id=project.pk,
        user_id=user.pk,
        project_role__in=tuple(roles),
    ).exists()


def project_role_for(*, user: User, project: Project) -> str | None:
    if not user.is_authenticated:
        return None
    return ProjectMembership.objects.filter(
        organization_id=project.organization_id, project_id=project.pk, user_id=user.pk
    ).values_list("project_role", flat=True).first()


def project_engineers(project: Project):
    """Return every engineer assigned through the canonical project membership."""
    return User.objects.filter(
        project_memberships__organization_id=project.organization_id,
        project_memberships__project_id=project.pk,
        project_memberships__project_role=ProjectMembership.Role.ENGINEER,
        is_active=True,
    ).distinct()


def is_project_owner(*, user: User, project: Project) -> bool:
    if not user.is_authenticated:
        return False
    return ProjectMembership.objects.filter(
        organization_id=project.organization_id,
        project_id=project.pk,
        user_id=user.pk,
        project_role=ProjectMembership.Role.OWNER,
    ).exists()


def can_authorize_project_finance(*, user: User, project: Project) -> bool:
    """Financial authority belongs exclusively to the confirmed project owner."""
    if not is_project_owner(user=user, project=project):
        return False
    try:
        return project.ownership.is_valid
    except ProjectOwnership.DoesNotExist:
        return False


def can_monitor_project_finance(*, user: User, project: Project) -> bool:
    return has_project_role(
        user=user, project=project, roles=PROJECT_FINANCE_MONITOR_ROLES
    )


def projects_visible_to(user: User, queryset: QuerySet[Project] | None = None):
    if queryset is None:
        queryset = Project.objects.all()
    if user.is_superuser:
        return queryset
    if not user.is_authenticated:
        return queryset.none()
    return queryset.filter(memberships__user_id=user.pk).distinct()
