from django.utils.translation import gettext_lazy as _
from hashlib import sha256
from secrets import token_urlsafe

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditEvent

from .models import Invitation, Notification, User


def send_transactional_email(*, subject, recipient, text_template, html_template, context):
    """Send a branded HTML message and retain a plain-text fallback."""
    email = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(text_template, context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
    )
    email.attach_alternative(render_to_string(html_template, context), "text/html")
    return email.send()


def create_notification(
    *, recipient, kind, title, message="", target_url="", actor=None, project=None
):
    """Create a notification in either an account or project context.

    A user's home organization must not prevent notifications for a project to
    which that user is explicitly assigned.  When ``project`` is supplied, the
    project membership is therefore the authorization boundary and the
    notification is stored under the project's organization.
    """
    if recipient.organization_id is None:
        raise ValidationError(_("Le destinataire doit appartenir à une organisation."))
    notification_organization_id = recipient.organization_id
    if project is not None:
        from apps.projects.models import ProjectMembership

        def is_project_recipient(user):
            return bool(
                user
                and (
                    user.is_superuser
                    or ProjectMembership.objects.filter(
                        project_id=project.pk,
                        organization_id=project.organization_id,
                        user_id=user.pk,
                    ).exists()
                )
            )

        def is_project_actor(user):
            return bool(
                is_project_recipient(user)
                or (
                    user
                    and user.is_staff
                    and user.role == User.Role.ADMIN
                    and user.organization_id == project.organization_id
                )
            )

        if not is_project_recipient(recipient):
            raise PermissionDenied("Le destinataire n'est pas affecté à ce projet.")
        if actor and not is_project_actor(actor):
            raise PermissionDenied("L'acteur n'est pas autorisé sur ce projet.")
        notification_organization_id = project.organization_id
    elif actor and actor.organization_id != recipient.organization_id and not actor.is_superuser:
        raise PermissionDenied(
            "L'acteur et le destinataire doivent appartenir à la même organisation."
        )
    return Notification.objects.create(
        organization_id=notification_organization_id,
        recipient=recipient,
        actor=actor,
        kind=kind,
        title=title[:160],
        message=message[:500],
        target_url=target_url[:500],
    )


@transaction.atomic
def activate_engineer(*, actor: User, engineer: User) -> User:
    is_platform_admin = actor.is_superuser
    is_organization_admin = (
        actor.is_staff
        and actor.role == User.Role.ADMIN
        and actor.organization_id == engineer.organization_id
    )
    if not (is_platform_admin or is_organization_admin):
        raise PermissionDenied("Vous ne pouvez pas activer ce compte.")
    if engineer.role != User.Role.ENGINEER:
        raise ValidationError(_("Seul un compte ingénieur peut être activé par ce workflow."))

    if not engineer.is_active:
        from apps.subscriptions.quotas import ensure_internal_member_capacity

        ensure_internal_member_capacity(
            engineer.organization, engineer.role, exclude_user=engineer
        )
        engineer.is_active = True
        engineer.save(update_fields=["is_active"])
        if engineer.organization_id:
            from apps.subscriptions.services import start_organization_trial

            start_organization_trial(organization=engineer.organization, actor=actor)
        AuditEvent.objects.create(
            organization=engineer.organization,
            actor=actor,
            action="account.engineer_activated",
            target_type="accounts.User",
            target_id=str(engineer.pk),
            metadata={"username": engineer.username},
        )
        if engineer.email:
            login_url = f"{settings.APP_BASE_URL}{reverse('accounts:login')}"
            logo_url = f"{settings.APP_BASE_URL}{static('images/Logo.png')}"
            transaction.on_commit(
                lambda: send_transactional_email(
                    subject="Votre compte ingénieur PIVOT est activé",
                    recipient=engineer.email,
                    text_template="emails/engineer_account_activated.txt",
                    html_template="emails/engineer_account_activated.html",
                    context={
                        "user": engineer,
                        "action_url": login_url,
                        "logo_url": logo_url,
                    },
                )
            )
    return engineer


def hash_invitation_token(raw_token: str) -> str:
    return sha256(raw_token.encode("utf-8")).hexdigest()


def _attach_invited_user(*, invitation: Invitation, user: User) -> None:
    if not invitation.project_id or not invitation.project_role:
        return
    from apps.projects.models import ProjectMembership, ProjectOwnership
    from apps.projects.services import record_actor_confirmation

    ProjectMembership.objects.update_or_create(
        project=invitation.project, user=user,
        defaults={"organization": invitation.organization, "project_role": invitation.project_role},
    )
    if invitation.project_role == ProjectMembership.Role.OWNER:
        ProjectOwnership.objects.update_or_create(
            project=invitation.project,
            defaults={
                "organization": invitation.organization, "owner": user,
                "is_confirmed": False, "terms_accepted": False,
            },
        )
    if invitation.project_role in {
        ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER,
    } and invitation.project.terms_versions.filter(is_current=True).exists():
        record_actor_confirmation(
            user=user, project=invitation.project,
            project_role=invitation.project_role, accepted=True,
        )


@transaction.atomic
def accept_invitation_for_existing_user(*, invitation: Invitation, user: User) -> User:
    invitation = Invitation.objects.select_for_update().select_related(
        "organization", "project"
    ).get(pk=invitation.pk)
    if not invitation.is_usable:
        raise ValidationError(_("Cette invitation n'est plus valide."))
    if user.email.strip().lower() != invitation.email.strip().lower():
        raise PermissionDenied("Cette invitation est destinée à une autre adresse e-mail.")
    if not user.is_active:
        raise ValidationError(_("Ce compte est désactivé."))
    _attach_invited_user(invitation=invitation, user=user)
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=("accepted_at",))
    return user


@transaction.atomic
def create_invitation(
    *, actor: User, email: str, role: str, project=None, project_role: str = ""
) -> tuple[Invitation, str]:
    project_owner_invite = False
    pivot_invite = bool(actor.is_superuser and project is not None)
    if project is not None:
        from apps.projects.access import has_project_role, is_project_owner
        from apps.projects.models import ProjectMembership, ProjectOnboarding

        project_owner_invite = is_project_owner(user=actor, project=project)
        project_engineer_invite = has_project_role(
            user=actor,
            project=project,
            roles={ProjectMembership.Role.ENGINEER},
        )
        contractor_preliminary_invite = (
            has_project_role(
                user=actor, project=project, roles={ProjectMembership.Role.CONTRACTOR}
            )
            and hasattr(project, "onboarding")
            and project.onboarding.route == ProjectOnboarding.Route.CONTRACTOR_LED
            and project.onboarding.status != ProjectOnboarding.Status.ACTIVE
        )
    else:
        project_engineer_invite = False
        contractor_preliminary_invite = False
    can_invite = (
        pivot_invite
        or project_owner_invite
        or project_engineer_invite
        or contractor_preliminary_invite
        or (
            project is None
            and actor.organization_id is not None
            and actor.role in {User.Role.ENGINEER, User.Role.ADMIN}
        )
    )
    if not can_invite:
        raise PermissionDenied("Vous ne pouvez pas inviter de membre.")
    allowed_roles = {User.Role.CLIENT, User.Role.SITE_MANAGER}
    if pivot_invite:
        allowed_roles = {
            User.Role.CLIENT, User.Role.CONTRACTOR, User.Role.SITE_MANAGER, User.Role.ENGINEER
        }
    elif project_owner_invite:
        allowed_roles = {User.Role.CONTRACTOR, User.Role.SITE_MANAGER, User.Role.ENGINEER}
    elif project_engineer_invite:
        allowed_roles = {User.Role.CONTRACTOR, User.Role.SITE_MANAGER, User.Role.ENGINEER}
    elif contractor_preliminary_invite:
        allowed_roles = {User.Role.CLIENT}
    if role not in allowed_roles:
        raise ValidationError(_("Ce rôle ne peut pas être invité."))
    if project is not None:
        if not pivot_invite and not project.memberships.filter(user=actor).exists():
            raise PermissionDenied
        expected_project_role = {
            User.Role.CLIENT: "owner",
            User.Role.CONTRACTOR: "contractor",
            User.Role.SITE_MANAGER: "site_manager",
            User.Role.ENGINEER: "engineer",
        }.get(role)
        if project_role != expected_project_role:
            raise ValidationError(_("Le rôle projet invité est invalide."))

    target_organization = project.organization if project is not None else actor.organization
    normalized_email = email.strip().lower()
    existing_user = User.objects.filter(email__iexact=normalized_email).first()
    if existing_user:
        if not existing_user.is_active:
            raise ValidationError(_("Le compte associé à cette adresse est désactivé."))
        if project is None:
            if existing_user.organization_id == target_organization.pk:
                raise ValidationError(_("Ce compte appartient déjà à votre organisation."))
            raise ValidationError(_("Une invitation sans projet ne peut pas rattacher un compte externe."))
        if project.memberships.filter(user=existing_user).exists():
            raise ValidationError(_("Cet utilisateur participe déjà à ce chantier."))
    else:
        from apps.subscriptions.quotas import ensure_internal_member_capacity

        ensure_internal_member_capacity(target_organization, role)
    if Invitation.objects.active().filter(
        organization=target_organization,
        email__iexact=normalized_email,
    ).exists():
        raise ValidationError(_("Une invitation active existe déjà pour cette adresse."))

    raw_token = token_urlsafe(32)
    invitation = Invitation.objects.create(
        organization=target_organization,
        invited_by=actor,
        email=normalized_email,
        role=role,
        project=project,
        project_role=project_role,
        token_hash=hash_invitation_token(raw_token),
    )
    return invitation, raw_token
