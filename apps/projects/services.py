from django.utils.translation import gettext_lazy as _
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.models import Notification
from apps.accounts.services import create_notification
from apps.audit.models import AuditEvent

from .models import (
    Project,
    ProjectMembership,
    ProjectOwnership,
    ProjectOwnershipHistory,
    ProjectOnboarding,
    ProjectActorConfirmation,
    ProjectTermsVersion,
    ProjectStatusHistory,
)
from .access import PROJECT_MANAGEMENT_ROLES, can_authorize_project_finance, has_project_role


def can_manage_project(*, actor: User, project: Project) -> bool:
    return has_project_role(user=actor, project=project, roles=PROJECT_MANAGEMENT_ROLES)


def ensure_can_create_project(actor: User) -> None:
    if actor.role == User.Role.CLIENT:
        return
    if actor.organization_id is None or actor.role not in {
        User.Role.ENGINEER, User.Role.CLIENT, User.Role.CONTRACTOR
    }:
        raise PermissionDenied(
            "Seul un ingénieur, un client ou un entrepreneur autorisé peut créer un projet."
        )
    from apps.subscriptions.quotas import ensure_project_capacity

    ensure_project_capacity(actor.organization)


def project_has_confirmed_owner(project: Project) -> bool:
    try:
        return project.ownership.is_valid
    except ProjectOwnership.DoesNotExist:
        return False


def project_finance_is_unlocked(project: Project) -> bool:
    """Legacy projects stay usable; onboarded projects unlock only after activation."""
    try:
        return project.onboarding.status == ProjectOnboarding.Status.ACTIVE
    except ProjectOnboarding.DoesNotExist:
        return True


def client_led_onboarding_missing(project: Project) -> tuple[str, ...]:
    missing = []
    if project.onboarding_conflicts.filter(status="open").exists():
        missing.append("onboarding_conflict")
    if not project_has_confirmed_owner(project):
        missing.append("ownership")
    if project.budget_amount <= 0:
        missing.append("budget")
    try:
        onboarding = project.onboarding
    except ProjectOnboarding.DoesNotExist:
        missing.append("conditions")
    else:
        if not onboarding.financial_conditions.strip():
            missing.append("conditions")
    if not project.memberships.filter(project_role=ProjectMembership.Role.CONTRACTOR).exists():
        missing.append("contractor")
    current_terms = project.terms_versions.filter(is_current=True).first()
    if not current_terms:
        missing.append("terms_version")
        return tuple(missing)
    try:
        ownership = project.ownership
    except ProjectOwnership.DoesNotExist:
        ownership = None
    if not ownership or current_terms.authority_owner_id != ownership.owner_id:
        missing.append("authority")
    if current_terms.budget_amount <= 0:
        missing.append("versioned_budget")
    if not current_terms.financial_conditions.strip():
        missing.append("versioned_conditions")
    memberships = list(project.memberships.filter(
        project_role__in=(
            ProjectMembership.Role.OWNER,
            ProjectMembership.Role.CONTRACTOR,
            ProjectMembership.Role.ENGINEER,
        )
    ).select_related("user"))
    if not any(m.project_role == ProjectMembership.Role.ENGINEER for m in memberships):
        missing.append("engineer")
    for membership in memberships:
        confirmation = current_terms.actor_confirmations.filter(
            user=membership.user, project_role=membership.project_role
        ).first()
        if not confirmation or not confirmation.is_valid:
            missing.append(f"{membership.project_role}_confirmation")
    return tuple(missing)


def record_actor_confirmation(*, user, project, project_role, accepted):
    membership = project.memberships.filter(user=user, project_role=project_role).first()
    if not membership:
        raise PermissionDenied("Cette participation ne vous est pas attribuée.")
    terms = project.terms_versions.get(is_current=True)
    existing = ProjectActorConfirmation.objects.filter(
        terms_version=terms, user=user, project_role=project_role
    ).first()
    if (
        existing
        and existing.status == ProjectActorConfirmation.Status.PENDING
        and existing.expires_at <= timezone.now()
    ):
        existing.status = ProjectActorConfirmation.Status.EXPIRED
        existing.save(update_fields=("status",))
        raise ValidationError(_("La demande de confirmation a expiré."))
    confirmation, confirmation_created = ProjectActorConfirmation.objects.update_or_create(
        terms_version=terms, user=user, project_role=project_role,
        defaults={
            "project": project, "organization": project.organization,
            "status": ProjectActorConfirmation.Status.ACCEPTED if accepted else ProjectActorConfirmation.Status.REJECTED,
            "expires_at": timezone.now() + timedelta(days=7),
            "responded_at": timezone.now(),
        },
    )
    AuditEvent.objects.create(
        organization=project.organization, actor=user,
        action="project.participation_accepted" if accepted else "project.participation_rejected",
        target_type="project", target_id=str(project.pk),
        metadata={"role": project_role, "terms_version": terms.version},
    )
    return confirmation


@transaction.atomic
def create_terms_version(*, actor, project, budget_amount, currency, financial_conditions, targeted_roles):
    current = project.terms_versions.select_for_update().filter(is_current=True).first()
    next_version = (current.version + 1) if current else 1
    if current:
        current.is_current = False
        current.save(update_fields=("is_current",))
    try:
        owner = project.ownership.owner
    except ProjectOwnership.DoesNotExist:
        owner = None
    terms = ProjectTermsVersion.objects.create(
        project=project, organization=project.organization, version=next_version,
        budget_amount=budget_amount, currency=currency,
        financial_conditions=financial_conditions, authority_owner=owner,
        created_by=actor, is_current=True,
    )
    if owner:
        ProjectActorConfirmation.objects.create(
            terms_version=terms, project=project, organization=project.organization,
            user=owner, project_role=ProjectMembership.Role.OWNER,
            status=ProjectActorConfirmation.Status.ACCEPTED,
            expires_at=timezone.now() + timedelta(days=7), responded_at=timezone.now(),
        )
    project.budget_amount = budget_amount
    project.save(update_fields=("budget_amount", "updated_at"))
    project.onboarding.financial_conditions = financial_conditions
    project.onboarding.conditions_version = f"v{next_version}"
    project.onboarding.save(update_fields=("financial_conditions", "conditions_version", "updated_at"))
    for membership in project.memberships.filter(project_role__in=targeted_roles):
        ProjectActorConfirmation.objects.create(
            terms_version=terms, project=project, organization=project.organization,
            user=membership.user, project_role=membership.project_role,
            expires_at=timezone.now() + timedelta(days=7),
        )
    AuditEvent.objects.create(
        organization=project.organization, actor=actor, action="project.terms_version_created",
        target_type="project", target_id=str(project.pk),
        metadata={"version": next_version, "targeted_roles": list(targeted_roles)},
    )
    return terms


@transaction.atomic
def activate_client_led_project(*, actor: User, project: Project):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if not can_authorize_project_finance(user=actor, project=project):
        raise PermissionDenied("Seul le propriétaire confirmé peut activer le projet.")
    onboarding = ProjectOnboarding.objects.select_for_update().get(project=project)
    if onboarding.status == ProjectOnboarding.Status.ACTIVE:
        return onboarding
    missing = client_led_onboarding_missing(project)
    if missing:
        raise ValidationError(_("Onboarding incomplet : ") + ", ".join(missing))
    onboarding.status = ProjectOnboarding.Status.ACTIVE
    onboarding.activated_by = actor
    onboarding.activated_at = timezone.now()
    onboarding.save(update_fields=("status", "activated_by", "activated_at", "updated_at"))
    if project.status != Project.Status.ONGOING:
        previous = project.status
        project.status = Project.Status.ONGOING
        project.save(update_fields=("status", "updated_at"))
        ProjectStatusHistory.objects.create(
            project=project, actor=actor, previous_status=previous, new_status=project.status
        )
    AuditEvent.objects.create(
        organization=project.organization,
        actor=actor,
        action="project.onboarding_activated",
        target_type="project",
        target_id=str(project.pk),
        metadata={"route": onboarding.route, "conditions_version": onboarding.conditions_version},
    )
    return onboarding


@transaction.atomic
def confirm_contractor_led_onboarding(*, actor: User, project: Project, confirmations: dict):
    project = Project.objects.select_for_update().get(pk=project.pk)
    onboarding = ProjectOnboarding.objects.select_for_update().get(project=project)
    if onboarding.route not in {
        ProjectOnboarding.Route.CONTRACTOR_LED,
        ProjectOnboarding.Route.PIVOT_LED,
    }:
        raise ValidationError(_("Ce projet ne suit pas un parcours préparé à confirmer."))
    required = {"confirm_project", "confirm_ownership", "confirm_contractor", "confirm_conditions"}
    if not all(confirmations.get(key) for key in required):
        raise ValidationError(_("Toutes les confirmations sont obligatoires."))
    ownership, ownership_created = confirm_project_ownership(
        actor=actor, project=project, terms_accepted=True
    )
    onboarding.status = ProjectOnboarding.Status.READY
    onboarding.save(update_fields=("status", "updated_at"))
    AuditEvent.objects.create(
        organization=project.organization,
        actor=actor,
        action=(
            "project.pivot_onboarding_confirmed"
            if onboarding.route == ProjectOnboarding.Route.PIVOT_LED
            else "project.contractor_onboarding_confirmed"
        ),
        target_type="project",
        target_id=str(project.pk),
        metadata={"contractor_confirmed": True, "conditions_version": onboarding.conditions_version},
    )
    return ownership, onboarding


@transaction.atomic
def confirm_project_ownership(*, actor: User, project: Project, terms_accepted: bool):
    if not terms_accepted:
        raise ValidationError(_("Vous devez accepter les conditions de propriété du chantier."))
    membership = ProjectMembership.objects.select_for_update().filter(
        project=project,
        organization=project.organization,
        user=actor,
        project_role=ProjectMembership.Role.OWNER,
    ).first()
    if membership is None:
        raise PermissionDenied("Seul le propriétaire désigné peut confirmer l'ownership.")
    ownership, ownership_created = ProjectOwnership.objects.select_for_update().get_or_create(
        project=project,
        defaults={"organization": project.organization, "owner": actor},
    )
    if ownership.owner_id != actor.pk:
        raise PermissionDenied("Vous n'êtes pas le propriétaire désigné.")
    if ownership.is_valid:
        return ownership, False
    ownership.is_confirmed = True
    ownership.confirmed_at = timezone.now()
    ownership.confirmed_by = actor
    ownership.terms_version = getattr(
        settings, "PIVOT_OWNERSHIP_TERMS_VERSION", "2026-09-v1"
    )
    ownership.terms_accepted = True
    ownership.full_clean()
    ownership.save()
    if project.terms_versions.filter(is_current=True).exists():
        project.terms_versions.filter(is_current=True).update(authority_owner=actor)
        record_actor_confirmation(
            user=actor, project=project,
            project_role=ProjectMembership.Role.OWNER, accepted=True,
        )
    AuditEvent.objects.create(
        organization=project.organization,
        actor=actor,
        action="project.ownership_confirmed",
        target_type="project",
        target_id=str(project.pk),
        metadata={"terms_version": ownership.terms_version},
    )
    return ownership, True


@transaction.atomic
def change_project_owner(*, actor: User, project: Project, new_owner: User, reason: str):
    project = Project.objects.select_for_update().get(pk=project.pk)
    if not can_manage_project(actor=actor, project=project):
        raise PermissionDenied
    reason = reason.strip()
    if not reason:
        raise ValidationError(_("Le motif du changement de propriétaire est obligatoire."))
    if (
        not new_owner.is_active
        or new_owner.organization_id != project.organization_id
        or new_owner.role != User.Role.CLIENT
    ):
        raise ValidationError(_("Le nouveau propriétaire doit être un client actif de l'organisation."))
    ownership = ProjectOwnership.objects.select_for_update().filter(project=project).first()
    previous_owner = ownership.owner if ownership else None
    if previous_owner and previous_owner.pk == new_owner.pk:
        raise ValidationError(_("Ce client est déjà le propriétaire désigné."))
    ProjectMembership.objects.filter(
        project=project, project_role=ProjectMembership.Role.OWNER
    ).delete()
    ProjectMembership.objects.update_or_create(
        project=project,
        user=new_owner,
        defaults={
            "organization": project.organization,
            "project_role": ProjectMembership.Role.OWNER,
        },
    )
    ownership, ownership_created = ProjectOwnership.objects.update_or_create(
        project=project,
        defaults={
            "organization": project.organization,
            "owner": new_owner,
            "is_confirmed": False,
            "confirmed_at": None,
            "confirmed_by": None,
            "terms_version": "",
            "terms_accepted": False,
        },
    )
    ProjectOwnershipHistory.objects.create(
        project=project,
        organization=project.organization,
        previous_owner=previous_owner,
        new_owner=new_owner,
        actor=actor,
        reason=reason,
    )
    AuditEvent.objects.create(
        organization=project.organization,
        actor=actor,
        action="project.owner_changed",
        target_type="project",
        target_id=str(project.pk),
        metadata={
            "previous_owner_id": previous_owner.pk if previous_owner else None,
            "new_owner_id": new_owner.pk,
            "reason": reason,
        },
    )
    return ownership


def can_reopen_completed_project(*, actor: User, project: Project) -> bool:
    """Politique de réouverture, isolée des vues pour pouvoir évoluer indépendamment."""
    return can_manage_project(actor=actor, project=project)


def available_status_transitions(*, actor: User, project: Project) -> tuple[str, ...]:
    if not can_manage_project(actor=actor, project=project):
        return ()
    if project.status == Project.Status.COMPLETE:
        if not can_reopen_completed_project(actor=actor, project=project):
            return ()
        return (Project.Status.PENDING, Project.Status.ONGOING)
    transitions = tuple(status for status in Project.Status.values if status != project.status)
    if not project_has_confirmed_owner(project):
        transitions = tuple(status for status in transitions if status == Project.Status.PENDING)
    return transitions


@transaction.atomic
def change_project_status(*, actor: User, project: Project, new_status: str) -> Project:
    locked_project = Project.objects.select_for_update().get(pk=project.pk)
    if new_status not in available_status_transitions(actor=actor, project=locked_project):
        raise PermissionDenied("Cette transition de statut n'est pas autorisée.")

    previous_status = locked_project.status
    if (
        previous_status == Project.Status.COMPLETE
        and new_status in {Project.Status.PENDING, Project.Status.ONGOING}
    ):
        from apps.subscriptions.quotas import ensure_project_capacity

        ensure_project_capacity(locked_project.organization)
    locked_project.status = new_status
    locked_project.save(update_fields=("status", "updated_at"))
    ProjectStatusHistory.objects.create(
        project=locked_project,
        actor=actor,
        previous_status=previous_status,
        new_status=new_status,
    )
    AuditEvent.objects.create(
        organization=locked_project.organization,
        actor=actor,
        action="project.status_changed",
        target_type="project",
        target_id=str(locked_project.pk),
        metadata={"previous_status": previous_status, "new_status": new_status},
    )
    for membership in locked_project.memberships.select_related("user"):
        if membership.user_id != actor.pk:
            create_notification(
                recipient=membership.user,
                actor=actor,
                kind=Notification.Kind.PROJECT,
                title="Statut du projet mis à jour",
                message=f"{locked_project.name} : {locked_project.get_status_display()}.",
                target_url=locked_project.get_absolute_url(),
                project=locked_project,
            )
    return locked_project
