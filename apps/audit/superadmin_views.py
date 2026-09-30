from django.utils.translation import gettext_lazy as _
import csv
import mimetypes
import os
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.models import Notification, User
from apps.accounts.services import (
    activate_engineer,
    create_invitation,
    create_notification,
    send_transactional_email,
)
from apps.ai_assistant.monitoring import assistant_health_snapshot
from apps.collaboration.models import ProjectComment, ProjectDocument, ProjectImage
from apps.collaboration.services import review_document
from apps.finance.models import PaymentTransaction, Withdrawal
from apps.finance.services import decide_withdrawal
from apps.inventory.models import StockItem
from apps.organizations.models import Organization
from apps.planning.models import ProjectStage
from apps.projects.models import (
    OnboardingConflictReview, Project, ProjectDispute, ProjectMembership, ProjectOnboarding,
    ProjectStatusHistory,
)
from apps.projects.disputes import add_dispute_observation, open_dispute, resolve_dispute
from apps.projects.services import client_led_onboarding_missing
from apps.subscriptions.models import OrganizationSubscription, SubscriptionEvent, SubscriptionPlan
from apps.subscriptions.quotas import quota_usage
from apps.subscriptions.services import add_calendar_months

from .forms import (
    OrganizationCreateForm,
    OrganizationUpdateForm,
    PlatformConfigurationForm,
    PlatformUserCreateForm,
    PlatformUserTransferForm,
    PlatformUserUpdateForm,
    PivotOnboardingForm,
    PivotProjectInvitationForm,
    PivotReviewerAssignmentForm,
    ProjectConciergeFollowUpForm,
    ProjectDisputeForm,
    ProjectDisputeObservationForm,
    ProjectDisputeResolutionForm,
    PilotPricingHypothesisForm,
    PilotRecommendationForm,
    PilotReviewDecisionForm,
    ProjectInterventionForm,
    SubscriptionInterventionForm,
    SubscriptionPlanForm,
)
from .models import AuditEvent, PilotReviewDecision, PlatformConfiguration
from .control_room import (
    adoption_metrics, concierge_checklist, pilot_economy_metrics, pilot_review_snapshot,
    trust_value_metrics,
)


def superuser_required(view_func):
    """Reserve a view to platform superusers, excluding organization admins."""

    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped


@require_GET
@superuser_required
def dashboard(request):
    organizations = Organization.objects.all()
    users = User.objects.filter(is_superuser=False)
    projects = Project.objects.all()
    pending_documents = ProjectDocument.objects.filter(status=ProjectDocument.Status.VERIFIED)
    pending_withdrawals = Withdrawal.objects.filter(status=Withdrawal.Status.PENDING)
    successful_payments = PaymentTransaction.objects.filter(
        status=PaymentTransaction.Status.SUCCESS
    )

    payment_totals = {
        row["currency"]: row["total"]
        for row in successful_payments.values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    }
    context = {
        "platform_stats": {
            "organizations": organizations.count(),
            "active_organizations": organizations.filter(status=Organization.Status.ACTIVE).count(),
            "users": users.count(),
            "active_users": users.filter(is_active=True).count(),
            "projects": projects.count(),
            "ongoing_projects": projects.filter(status=Project.Status.ONGOING).count(),
            "pending_validations": pending_documents.count() + pending_withdrawals.count(),
        },
        "project_breakdown": {
            "pending": projects.filter(status=Project.Status.PENDING).count(),
            "ongoing": projects.filter(status=Project.Status.ONGOING).count(),
            "complete": projects.filter(status=Project.Status.COMPLETE).count(),
        },
        "acquisition_routes": {
            route: projects.filter(onboarding__route=route).count()
            for route, route_label in ProjectOnboarding.Route.choices
        },
        "payment_totals": payment_totals,
        "pending_withdrawal_total": pending_withdrawals.aggregate(total=Sum("amount"))["total"]
        or 0,
        "recent_organizations": organizations.order_by("-created_at")[:5],
        "recent_projects": projects.select_related("organization", "engineer").order_by(
            "-updated_at"
        )[:6],
        "pending_documents": pending_documents.select_related(
            "organization", "project", "uploaded_by"
        ).order_by("-uploaded_at")[:4],
        "pending_withdrawals": pending_withdrawals.select_related(
            "organization", "project", "requested_by"
        ).order_by("-requested_at")[:4],
        "assistant_health": assistant_health_snapshot(),
    }
    return render(request, "superadmin/dashboard.html", context)


@require_GET
@superuser_required
def organization_list(request):
    organizations = Organization.objects.annotate(
        user_count=Count("users", distinct=True),
        project_count=Count("projects", distinct=True),
    )
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "").strip()
    selected_sort = request.GET.get("sort", "name").strip()
    if query:
        organizations = organizations.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(users__username__icontains=query)
            | Q(users__email__icontains=query)
        ).distinct()
    if selected_status in Organization.Status.values:
        organizations = organizations.filter(status=selected_status)
    elif selected_status:
        selected_status = ""
    sort_fields = {
        "name": "name",
        "newest": "-created_at",
        "users": "-user_count",
        "projects": "-project_count",
    }
    if selected_sort not in sort_fields:
        selected_sort = "name"
    organizations = organizations.order_by(sort_fields[selected_sort], "name")
    page = Paginator(organizations, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/organizations/list.html",
        {
            "organization_page": page,
            "query": query,
            "selected_status": selected_status,
            "selected_sort": selected_sort,
            "organization_statuses": Organization.Status.choices,
            "organization_create_form": OrganizationCreateForm(),
            "organization_totals": {
                "all": Organization.objects.count(),
                "active": Organization.objects.filter(status=Organization.Status.ACTIVE).count(),
                "suspended": Organization.objects.filter(
                    status=Organization.Status.SUSPENDED
                ).count(),
                "archived": Organization.objects.filter(
                    status=Organization.Status.ARCHIVED
                ).count(),
            },
        },
    )


def _send_initial_account_link(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    url = request.build_absolute_uri(
        reverse("accounts:password-reset-confirm", kwargs={"uidb64": uid, "token": token})
    )
    send_transactional_email(
        subject="Activez votre compte PIVOT",
        recipient=user.email,
        text_template="emails/account_activation.txt",
        html_template="emails/account_activation.html",
        context={
            "user": user,
            "action_url": url,
            "logo_url": request.build_absolute_uri(static("images/Logo.png")),
        },
    )


@require_POST
@superuser_required
def organization_create(request):
    form = OrganizationCreateForm(request.POST)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de création est obligatoire."))
    elif form.is_valid():
        with transaction.atomic():
            organization = Organization.objects.create(
                name=form.cleaned_data["name"], slug=form.cleaned_data["slug"]
            )
            role = form.cleaned_data["first_role"]
            first_user = User(
                organization=organization,
                username=form.cleaned_data["first_username"],
                email=form.cleaned_data["first_email"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                role=role,
                is_active=True,
                is_staff=role == User.Role.ADMIN,
            )
            first_user.set_unusable_password()
            first_user.save()
            AuditEvent.objects.create(
                organization=organization,
                actor=request.user,
                action="organization.created",
                target_type="organization",
                target_id=str(organization.pk),
                metadata={"first_user_role": role},
            )
            transaction.on_commit(lambda: _send_initial_account_link(request, first_user))
        messages.success(request, _("L’organisation et son premier responsable ont été créés."))
        return redirect("superadmin:organization-detail", pk=organization.pk)
    else:
        errors = " ".join(error for values in form.errors.values() for error in values)
        messages.error(request, errors or "Les informations de création sont invalides.")
    return redirect("superadmin:organization-list")


@require_POST
@superuser_required
def organization_update(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    previous = {"name": organization.name, "slug": organization.slug}
    form = OrganizationUpdateForm(request.POST, instance=organization)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de modification est obligatoire."))
    elif form.is_valid():
        with transaction.atomic():
            updated = form.save()
            changed_fields = [
                field for field in ("name", "slug") if previous[field] != getattr(updated, field)
            ]
            if changed_fields:
                AuditEvent.objects.create(
                    organization=updated,
                    actor=request.user,
                    action="organization.updated",
                    target_type="organization",
                    target_id=str(updated.pk),
                    metadata={"changed_fields": changed_fields},
                )
        messages.success(request, _("Les informations de l’organisation ont été modifiées."))
    else:
        errors = " ".join(error for values in form.errors.values() for error in values)
        messages.error(request, errors or "Les informations de modification sont invalides.")
    return redirect("superadmin:organization-detail", pk=pk)


@require_GET
@superuser_required
def organization_detail(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    users = organization.users.order_by("role", "username")
    projects = organization.projects.select_related("engineer").order_by("-updated_at")
    payment_totals = {
        row["currency"]: row["total"]
        for row in PaymentTransaction.objects.filter(
            organization=organization, status=PaymentTransaction.Status.SUCCESS
        )
        .values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    }
    dependency_counts = _organization_dependency_counts(organization)
    return render(
        request,
        "superadmin/organizations/detail.html",
        {
            "organization": organization,
            "organization_update_form": OrganizationUpdateForm(instance=organization),
            "organization_stats": {
                "users": users.count(),
                "active_users": users.filter(is_active=True).count(),
                "engineers": users.filter(role=User.Role.ENGINEER).count(),
                "projects": projects.count(),
                "ongoing_projects": projects.filter(status=Project.Status.ONGOING).count(),
            },
            "organization_users": users[:8],
            "organization_projects": projects[:8],
            "payment_totals": payment_totals,
            "recent_audit_events": organization.audit_events.select_related("actor")[:8],
            "dependency_counts": dependency_counts,
            "can_delete_organization": not any(dependency_counts.values()),
        },
    )


def _organization_dependency_counts(organization):
    return {
        "users": organization.users.count(),
        "projects": organization.projects.count(),
        "audits": organization.audit_events.count(),
        "invitations": organization.invitations.count(),
        "notifications": organization.notifications.count(),
        "memberships": organization.project_memberships.count(),
        "payments": organization.paymenttransaction_set.count(),
        "withdrawals": organization.withdrawal_set.count(),
        "documents": organization.projectdocument_set.count(),
        "photos": organization.projectimage_set.count(),
        "comments": organization.projectcomment_set.count(),
        "stocks": organization.stock_items.count(),
        "stock_movements": organization.stock_movements.count(),
        "stages": organization.project_stages.count(),
    }


@require_POST
@superuser_required
def organization_lifecycle(request, pk):
    action = request.POST.get("action", "")
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de l’opération est obligatoire."))
        return redirect("superadmin:organization-detail", pk=pk)
    with transaction.atomic():
        organization = get_object_or_404(Organization.objects.select_for_update(), pk=pk)
        if action == "archive":
            if organization.status == Organization.Status.ARCHIVED:
                messages.info(request, _("Cette organisation est déjà archivée."))
            else:
                previous_status = organization.status
                organization.status = Organization.Status.ARCHIVED
                organization.save(update_fields=("status", "updated_at"))
                AuditEvent.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="organization.archived",
                    target_type="organization",
                    target_id=str(organization.pk),
                    metadata={"previous_status": previous_status},
                )
                messages.success(
                    request, _("L’organisation a été archivée et ses accès sont bloqués.")
                )
            return redirect("superadmin:organization-detail", pk=pk)
        if action == "restore":
            if organization.status != Organization.Status.ARCHIVED:
                messages.error(request, _("Seule une organisation archivée peut être restaurée."))
            else:
                organization.status = Organization.Status.ACTIVE
                organization.save(update_fields=("status", "updated_at"))
                AuditEvent.objects.create(
                    organization=organization,
                    actor=request.user,
                    action="organization.restored",
                    target_type="organization",
                    target_id=str(organization.pk),
                    metadata={"new_status": Organization.Status.ACTIVE},
                )
                messages.success(request, _("L’organisation a été restaurée."))
            return redirect("superadmin:organization-detail", pk=pk)
        if action == "delete":
            if request.POST.get("confirmation_name", "").strip() != organization.name:
                messages.error(request, _("Le nom de confirmation ne correspond pas."))
                return redirect("superadmin:organization-detail", pk=pk)
            if any(_organization_dependency_counts(organization).values()):
                messages.error(
                    request,
                    _("Cette organisation possède un historique et doit être archivée plutôt que supprimée."),
                )
                return redirect("superadmin:organization-detail", pk=pk)
            organization_id = organization.pk
            organization.delete()
            AuditEvent.objects.create(
                actor=request.user,
                action="organization.deleted",
                target_type="organization",
                target_id=str(organization_id),
                metadata={},
            )
            messages.success(request, _("L’organisation vide a été supprimée définitivement."))
            return redirect("superadmin:organization-list")
    messages.error(request, _("L’opération demandée est invalide."))
    return redirect("superadmin:organization-detail", pk=pk)


@require_POST
@superuser_required
def organization_status(request, pk):
    requested_status = request.POST.get("status", "")
    if requested_status not in {Organization.Status.ACTIVE, Organization.Status.SUSPENDED}:
        messages.error(request, _("Le statut demandé est invalide."))
        return redirect("superadmin:organization-detail", pk=pk)

    with transaction.atomic():
        organization = get_object_or_404(Organization.objects.select_for_update(), pk=pk)
        if organization.status == Organization.Status.ARCHIVED:
            messages.error(request, _("Restaurez l’organisation avant de modifier son statut."))
            return redirect("superadmin:organization-detail", pk=pk)
        previous_status = organization.status
        if previous_status != requested_status:
            organization.status = requested_status
            organization.save(update_fields=("status", "updated_at"))
            AuditEvent.objects.create(
                organization=organization,
                actor=request.user,
                action="organization.status_changed",
                target_type="organization",
                target_id=str(organization.pk),
                metadata={"previous_status": previous_status, "new_status": requested_status},
            )
            messages.success(
                request,
                _("L’organisation a été activée.")
                if requested_status == Organization.Status.ACTIVE
                else "L’organisation a été suspendue.",
            )
        else:
            messages.info(request, _("L’organisation possède déjà ce statut."))
    return redirect("superadmin:organization-detail", pk=pk)


@require_GET
@superuser_required
def user_list(request):
    users = User.objects.select_related("organization").annotate(
        managed_project_count=Count("managed_projects", distinct=True),
        membership_count=Count("project_memberships", distinct=True),
    )
    query = request.GET.get("q", "").strip()
    selected_role = request.GET.get("role", "").strip()
    selected_organization = request.GET.get("organization", "").strip()
    selected_status = request.GET.get("status", "").strip()
    selected_sort = request.GET.get("sort", "newest").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    adoption_from = parse_date(request.GET.get("adoption_from", ""))
    adoption_to = parse_date(request.GET.get("adoption_to", ""))

    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    if selected_role in User.Role.values:
        users = users.filter(role=selected_role)
    elif selected_role:
        selected_role = ""
    if selected_organization.isdigit():
        users = users.filter(organization_id=int(selected_organization))
    elif selected_organization:
        selected_organization = ""
    if selected_status == "active":
        users = users.filter(is_active=True)
    elif selected_status == "inactive":
        users = users.filter(is_active=False)
    elif selected_status:
        selected_status = ""
    if date_from:
        users = users.filter(date_joined__date__gte=date_from)
    if date_to:
        users = users.filter(date_joined__date__lte=date_to)
    sort_fields = {
        "newest": "-date_joined",
        "oldest": "date_joined",
        "username": "username",
        "organization": "organization__name",
    }
    if selected_sort not in sort_fields:
        selected_sort = "newest"
    users = users.order_by(sort_fields[selected_sort], "pk")
    page = Paginator(users, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/users/list.html",
        {
            "user_page": page,
            "query": query,
            "selected_role": selected_role,
            "selected_organization": selected_organization,
            "selected_status": selected_status,
            "selected_sort": selected_sort,
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "adoption_from": request.GET.get("adoption_from", ""),
            "adoption_to": request.GET.get("adoption_to", ""),
            "adoption_metrics": adoption_metrics(
                date_from=adoption_from, date_to=adoption_to
            ),
            "trust_metrics": trust_value_metrics(
                date_from=adoption_from, date_to=adoption_to
            ),
            "economy_metrics": pilot_economy_metrics(
                date_from=adoption_from, date_to=adoption_to
            ),
            "recommendation_form": PilotRecommendationForm(),
            "pricing_hypothesis_form": PilotPricingHypothesisForm(),
            "user_roles": User.Role.choices,
            "user_create_form": PlatformUserCreateForm(),
            "organizations": Organization.objects.order_by("name"),
            "user_totals": {
                "all": User.objects.count(),
                "active": User.objects.filter(is_active=True).count(),
                "inactive": User.objects.filter(is_active=False).count(),
                "superusers": User.objects.filter(is_superuser=True).count(),
            },
        },
    )


@require_GET
@superuser_required
def user_detail(request, pk):
    selected_user = get_object_or_404(User.objects.select_related("organization"), pk=pk)
    managed_projects = selected_user.managed_projects.select_related("organization").order_by(
        "-updated_at"
    )
    memberships = selected_user.project_memberships.select_related(
        "project", "organization"
    ).order_by("-created_at")
    return render(
        request,
        "superadmin/users/detail.html",
        {
            "selected_user": selected_user,
            "user_update_form": PlatformUserUpdateForm(instance=selected_user),
            "user_transfer_form": PlatformUserTransferForm(user=selected_user),
            "user_stats": {
                "managed_projects": managed_projects.count(),
                "memberships": memberships.count(),
                "comments": selected_user.project_comments.filter(is_deleted=False).count(),
                "documents": selected_user.uploaded_documents.count(),
            },
            "managed_projects": managed_projects[:6],
            "project_memberships": memberships[:6],
            "recent_user_audit_events": selected_user.audit_events.select_related("organization")[
                :8
            ],
            "can_send_password_reset": bool(
                selected_user.email
                and selected_user.is_active
                and selected_user.has_usable_password()
            ),
        },
    )


@require_POST
@superuser_required
def user_create(request):
    form = PlatformUserCreateForm(request.POST)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de création est obligatoire."))
    elif form.is_valid():
        with transaction.atomic():
            role = form.cleaned_data["role"]
            account = User(
                organization=form.cleaned_data["organization"],
                username=form.cleaned_data["username"],
                email=form.cleaned_data["email"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                role=role,
                is_active=True,
                is_staff=role == User.Role.ADMIN,
            )
            account.set_unusable_password()
            account.save()
            AuditEvent.objects.create(
                organization=account.organization,
                actor=request.user,
                action="user.created",
                target_type="user",
                target_id=str(account.pk),
                metadata={"role": role},
            )
            transaction.on_commit(lambda: _send_initial_account_link(request, account))
        messages.success(request, _("L’utilisateur a été créé et son lien d’activation envoyé."))
        return redirect("superadmin:user-detail", pk=account.pk)
    else:
        errors = " ".join(error for values in form.errors.values() for error in values)
        messages.error(request, errors or "Les informations utilisateur sont invalides.")
    return redirect("superadmin:user-list")


@require_POST
@superuser_required
def user_update(request, pk):
    selected_user = get_object_or_404(User, pk=pk)
    tracked_fields = ("username", "first_name", "last_name", "email", "role")
    previous = {field: getattr(selected_user, field) for field in tracked_fields}
    form = PlatformUserUpdateForm(request.POST, instance=selected_user)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de modification est obligatoire."))
    elif form.is_valid():
        with transaction.atomic():
            updated = form.save(commit=False)
            updated.is_staff = updated.role == User.Role.ADMIN or updated.is_superuser
            updated.save()
            changed_fields = [
                field for field in tracked_fields if previous[field] != getattr(updated, field)
            ]
            if changed_fields:
                AuditEvent.objects.create(
                    organization=updated.organization,
                    actor=request.user,
                    action="user.updated",
                    target_type="user",
                    target_id=str(updated.pk),
                    metadata={"changed_fields": changed_fields},
                )
        messages.success(request, _("Les informations utilisateur ont été modifiées."))
    else:
        errors = " ".join(error for values in form.errors.values() for error in values)
        messages.error(request, errors or "La modification est invalide.")
    return redirect("superadmin:user-detail", pk=pk)


@require_POST
@superuser_required
def user_transfer(request, pk):
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation du transfert est obligatoire."))
        return redirect("superadmin:user-detail", pk=pk)

    with transaction.atomic():
        selected_user = get_object_or_404(
            User.objects.select_for_update().select_related("organization"), pk=pk
        )
        form = PlatformUserTransferForm(request.POST, user=selected_user)
        if not form.is_valid():
            errors = " ".join(error for values in form.errors.values() for error in values)
            messages.error(request, errors or "Le transfert demandé est invalide.")
            return redirect("superadmin:user-detail", pk=pk)

        source_organization = selected_user.organization
        target_organization = form.cleaned_data["target_organization"]
        project_replacement = form.cleaned_data.get("project_replacement")
        membership_replacement = form.cleaned_data.get("membership_replacement")
        reason = form.cleaned_data["reason"].strip()
        if not reason:
            messages.error(request, _("Le motif du transfert est obligatoire."))
            return redirect("superadmin:user-detail", pk=pk)

        memberships = list(
            selected_user.project_memberships.select_for_update().select_related("project")
        )
        managed_projects = [
            membership.project_id
            for membership in memberships
            if membership.project_role == ProjectMembership.Role.ENGINEER
        ]
        # Synchronisation transitoire de l'ancienne colonne; les droits sont
        # exclusivement portés par ProjectMembership.
        if managed_projects:
            Project.objects.filter(pk__in=managed_projects).update(engineer=project_replacement)
        reassigned_memberships = 0
        for membership in memberships:
            replacement = (
                project_replacement
                if membership.project_id in managed_projects
                and membership.project_role == ProjectMembership.Role.ENGINEER
                else membership_replacement
            )
            if replacement is None:
                continue
            existing = membership.project.memberships.filter(user=replacement).exists()
            if existing:
                membership.delete()
            else:
                membership.user = replacement
                membership.save(update_fields=("user",))
            reassigned_memberships += 1

        selected_user.organization = target_organization
        selected_user.save(update_fields=("organization",))
        AuditEvent.objects.create(
            organization=target_organization,
            actor=request.user,
            action="user.transferred",
            target_type="user",
            target_id=str(selected_user.pk),
            metadata={
                "source_organization_id": source_organization.pk,
                "target_organization_id": target_organization.pk,
                "reassigned_projects": len(managed_projects),
                "reassigned_memberships": reassigned_memberships,
                "reason": reason,
            },
        )
        create_notification(
            recipient=selected_user,
            actor=request.user,
            kind=Notification.Kind.ACCOUNT,
            title="Votre organisation a été modifiée",
            message=f"Votre compte appartient maintenant à {target_organization.name}.",
            target_url=reverse("accounts:post-login"),
        )
    messages.success(request, _("L’utilisateur et ses dépendances ont été transférés."))
    return redirect("superadmin:user-detail", pk=pk)


@require_POST
@superuser_required
def user_status(request, pk):
    requested_status = request.POST.get("status", "")
    if requested_status not in {"active", "inactive"}:
        messages.error(request, _("Le statut demandé est invalide."))
        return redirect("superadmin:user-detail", pk=pk)

    with transaction.atomic():
        selected_user = get_object_or_404(User.objects.select_for_update(), pk=pk)
        activate = requested_status == "active"
        if not activate and selected_user.pk == request.user.pk:
            messages.error(request, _("Vous ne pouvez pas suspendre votre propre compte."))
            return redirect("superadmin:user-detail", pk=pk)
        if (
            not activate
            and selected_user.is_superuser
            and not User.objects.filter(is_superuser=True, is_active=True)
            .exclude(pk=selected_user.pk)
            .exists()
        ):
            messages.error(
                request, _("Le dernier super-administrateur actif ne peut pas être suspendu.")
            )
            return redirect("superadmin:user-detail", pk=pk)
        previous_status = "active" if selected_user.is_active else "inactive"
        if selected_user.is_active != activate:
            if activate and selected_user.role == User.Role.ENGINEER:
                activate_engineer(actor=request.user, engineer=selected_user)
            else:
                selected_user.is_active = activate
                selected_user.save(update_fields=("is_active",))
            AuditEvent.objects.create(
                organization=selected_user.organization,
                actor=request.user,
                action="user.status_changed",
                target_type="user",
                target_id=str(selected_user.pk),
                metadata={"previous_status": previous_status, "new_status": requested_status},
            )
            messages.success(
                request,
                _("Le compte utilisateur a été activé.")
                if activate
                else "Le compte utilisateur a été suspendu.",
            )
        else:
            messages.info(request, _("Le compte possède déjà ce statut."))
    return redirect("superadmin:user-detail", pk=pk)


@require_POST
@superuser_required
def user_password_reset(request, pk):
    selected_user = get_object_or_404(User, pk=pk)
    if (
        not selected_user.email
        or not selected_user.is_active
        or not selected_user.has_usable_password()
    ):
        messages.error(request, _("Ce compte ne peut pas recevoir un lien de réinitialisation."))
        return redirect("superadmin:user-detail", pk=pk)

    form = PasswordResetForm({"email": selected_user.email})
    if form.is_valid():
        form.save(
            request=request,
            use_https=request.is_secure(),
            email_template_name="accounts/password_reset_email.txt",
            html_email_template_name="emails/password_reset.html",
            subject_template_name="accounts/password_reset_subject.txt",
        )
        AuditEvent.objects.create(
            organization=selected_user.organization,
            actor=request.user,
            action="user.password_reset_requested",
            target_type="user",
            target_id=str(selected_user.pk),
            metadata={},
        )
        messages.success(request, _("Le lien sécurisé de réinitialisation a été envoyé."))
    return redirect("superadmin:user-detail", pk=pk)


@require_POST
@superuser_required
def pilot_recommendation_create(request):
    form = PilotRecommendationForm(request.POST)
    if request.POST.get("confirmed") == "yes" and form.is_valid():
        recommendation = form.save(commit=False)
        recommendation.recorded_by = request.user
        recommendation.save()
        AuditEvent.objects.create(
            organization=recommendation.organization, actor=request.user,
            action="pilot.recommendation_recorded", target_type="pilot_recommendation",
            target_id=str(recommendation.pk), metadata={
                "respondent_role": recommendation.respondent_role,
                "score": recommendation.score,
            },
        )
        messages.success(request, _("Le score de recommandation a été enregistré."))
    else:
        messages.error(request, _("La mesure de recommandation est invalide."))
    return redirect("superadmin:project-list")


@require_POST
@superuser_required
def pilot_pricing_hypothesis_create(request):
    form = PilotPricingHypothesisForm(request.POST)
    if request.POST.get("confirmed") == "yes" and form.is_valid():
        hypothesis = form.save(commit=False)
        hypothesis.recorded_by = request.user
        hypothesis.save()
        AuditEvent.objects.create(
            organization=None, actor=request.user,
            action="pilot.pricing_hypothesis_recorded", target_type="pricing_hypothesis",
            target_id=str(hypothesis.pk), metadata={
                "segment": hypothesis.segment, "plan": hypothesis.plan.code,
                "proposed_monthly_price": str(hypothesis.proposed_monthly_price),
                "sample_size": hypothesis.sample_size,
                "positive_responses": hypothesis.positive_responses,
                "status": hypothesis.status,
            },
        )
        messages.success(request, _("L’hypothèse de pricing a été enregistrée."))
    else:
        messages.error(request, _("L’hypothèse de pricing est invalide."))
    return redirect("superadmin:project-list")
    query = request.GET.get("q", "").strip()
    selected_organization = request.GET.get("organization", "").strip()
    selected_status = request.GET.get("status", "").strip()
    selected_engineer = request.GET.get("engineer", "").strip()
    selected_route = request.GET.get("route", "").strip()
    selected_onboarding_status = request.GET.get("onboarding_status", "").strip()
    selected_city = request.GET.get("city", "").strip()
    selected_blockage = request.GET.get("blockage", "").strip()
    selected_sort = request.GET.get("sort", "updated").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))

    if query:
        projects = projects.filter(
            Q(name__icontains=query)
            | Q(location__icontains=query)
            | Q(description__icontains=query)
        )
    if selected_organization.isdigit():
        projects = projects.filter(organization_id=int(selected_organization))
    elif selected_organization:
        selected_organization = ""
    if selected_status in Project.Status.values:
        projects = projects.filter(status=selected_status)
    elif selected_status:
        selected_status = ""
    if selected_engineer.isdigit():
        projects = projects.filter(engineer_id=int(selected_engineer))
    elif selected_engineer:
        selected_engineer = ""
    if selected_route in ProjectOnboarding.Route.values:
        projects = projects.filter(onboarding__route=selected_route)
    elif selected_route:
        selected_route = ""
    if selected_onboarding_status in ProjectOnboarding.Status.values:
        projects = projects.filter(onboarding__status=selected_onboarding_status)
    elif selected_onboarding_status:
        selected_onboarding_status = ""
    if selected_city:
        projects = projects.filter(location__iexact=selected_city)
    if selected_blockage not in {"", "blocked", "clear"}:
        selected_blockage = ""
    if date_from:
        projects = projects.filter(project_date__gte=date_from)
    if date_to:
        projects = projects.filter(project_date__lte=date_to)
    sort_fields = {
        "updated": "-updated_at",
        "newest": "-project_date",
        "oldest": "project_date",
        "name": "name",
        "budget": "-budget_amount",
    }
    if selected_sort not in sort_fields:
        selected_sort = "updated"
    projects = list(projects.order_by(sort_fields[selected_sort], "name"))
    blocker_labels = {
        "onboarding_conflict": "Conflit d’onboarding",
        "ownership": "Propriétaire non confirmé",
        "budget": "Budget manquant",
        "conditions": "Conditions manquantes",
        "contractor": "Entrepreneur manquant",
        "terms_version": "Conditions non versionnées",
        "authority": "Autorité financière non confirmée",
        "versioned_budget": "Budget versionné manquant",
        "versioned_conditions": "Conditions versionnées manquantes",
        "engineer": "Ingénieur manquant",
    }
    for project in projects:
        if hasattr(project, "onboarding"):
            raw_blockers = client_led_onboarding_missing(project)
            project.control_blockers = [
                blocker_labels.get(code, "Confirmation d’acteur en attente")
                for code in raw_blockers
            ]
        else:
            project.control_blockers = ["Route d’onboarding non initialisée"]
        project.is_activation_ready = bool(
            hasattr(project, "onboarding")
            and project.onboarding.status != ProjectOnboarding.Status.ACTIVE
            and not project.control_blockers
        )
    if selected_blockage == "blocked":
        projects = [project for project in projects if project.control_blockers]
    elif selected_blockage == "clear":
        projects = [project for project in projects if not project.control_blockers]
    page = Paginator(projects, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/projects/list.html",
        {
            "project_page": page,
            "query": query,
            "selected_organization": selected_organization,
            "selected_status": selected_status,
            "selected_engineer": selected_engineer,
            "selected_route": selected_route,
            "selected_onboarding_status": selected_onboarding_status,
            "selected_city": selected_city,
            "selected_blockage": selected_blockage,
            "selected_sort": selected_sort,
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "organizations": Organization.objects.order_by("name"),
            "engineers": User.objects.filter(role=User.Role.ENGINEER)
            .select_related("organization")
            .order_by("organization__name", "username"),
            "project_statuses": Project.Status.choices,
            "onboarding_routes": ProjectOnboarding.Route.choices,
            "onboarding_statuses": ProjectOnboarding.Status.choices,
            "cities": Project.objects.exclude(location="").order_by("location").values_list(
                "location", flat=True
            ).distinct(),
            "project_totals": {
                "all": Project.objects.count(),
                "pending": Project.objects.filter(status=Project.Status.PENDING).count(),
                "ongoing": Project.objects.filter(status=Project.Status.ONGOING).count(),
                "complete": Project.objects.filter(status=Project.Status.COMPLETE).count(),
            },
        },
    )


@require_GET
@superuser_required
def project_list(request):
    projects = Project.objects.select_related("organization", "engineer", "onboarding").annotate(
        member_count=Count("memberships", distinct=True), stage_count=Count("stages", distinct=True)
    )
    query = request.GET.get("q", "").strip()
    selected_organization = request.GET.get("organization", "").strip()
    selected_status = request.GET.get("status", "").strip()
    selected_engineer = request.GET.get("engineer", "").strip()
    selected_route = request.GET.get("route", "").strip()
    selected_onboarding_status = request.GET.get("onboarding_status", "").strip()
    selected_city = request.GET.get("city", "").strip()
    selected_blockage = request.GET.get("blockage", "").strip()
    selected_sort = request.GET.get("sort", "updated").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    adoption_from = parse_date(request.GET.get("adoption_from", ""))
    adoption_to = parse_date(request.GET.get("adoption_to", ""))
    if query:
        projects = projects.filter(Q(name__icontains=query) | Q(location__icontains=query) | Q(description__icontains=query))
    if selected_organization.isdigit(): projects = projects.filter(organization_id=int(selected_organization))
    elif selected_organization: selected_organization = ""
    if selected_status in Project.Status.values: projects = projects.filter(status=selected_status)
    elif selected_status: selected_status = ""
    if selected_engineer.isdigit(): projects = projects.filter(engineer_id=int(selected_engineer))
    elif selected_engineer: selected_engineer = ""
    if selected_route in ProjectOnboarding.Route.values: projects = projects.filter(onboarding__route=selected_route)
    elif selected_route: selected_route = ""
    if selected_onboarding_status in ProjectOnboarding.Status.values: projects = projects.filter(onboarding__status=selected_onboarding_status)
    elif selected_onboarding_status: selected_onboarding_status = ""
    if selected_city: projects = projects.filter(location__iexact=selected_city)
    if selected_blockage not in {"", "blocked", "clear"}: selected_blockage = ""
    if date_from: projects = projects.filter(project_date__gte=date_from)
    if date_to: projects = projects.filter(project_date__lte=date_to)
    sort_fields = {"updated": "-updated_at", "newest": "-project_date", "oldest": "project_date", "name": "name", "budget": "-budget_amount"}
    if selected_sort not in sort_fields: selected_sort = "updated"
    projects = list(projects.order_by(sort_fields[selected_sort], "name"))
    labels = {"onboarding_conflict": "Conflit d’onboarding", "ownership": "Propriétaire non confirmé", "budget": "Budget manquant", "conditions": "Conditions manquantes", "contractor": "Entrepreneur manquant", "terms_version": "Conditions non versionnées", "authority": "Autorité financière non confirmée", "versioned_budget": "Budget versionné manquant", "versioned_conditions": "Conditions versionnées manquantes", "engineer": "Ingénieur manquant"}
    for project in projects:
        raw = client_led_onboarding_missing(project) if hasattr(project, "onboarding") else ("route",)
        project.control_blockers = [labels.get(code, "Confirmation d’acteur en attente" if code != "route" else "Route d’onboarding non initialisée") for code in raw]
    if selected_blockage == "blocked": projects = [p for p in projects if p.control_blockers]
    elif selected_blockage == "clear": projects = [p for p in projects if not p.control_blockers]
    page = Paginator(projects, 15).get_page(request.GET.get("page"))
    return render(request, "superadmin/projects/list.html", {
        "project_page": page, "query": query, "selected_organization": selected_organization,
        "selected_status": selected_status, "selected_engineer": selected_engineer,
        "selected_route": selected_route, "selected_onboarding_status": selected_onboarding_status,
        "selected_city": selected_city, "selected_blockage": selected_blockage,
        "selected_sort": selected_sort, "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""), "adoption_from": request.GET.get("adoption_from", ""),
        "adoption_to": request.GET.get("adoption_to", ""),
        "adoption_metrics": adoption_metrics(date_from=adoption_from, date_to=adoption_to),
        "trust_metrics": trust_value_metrics(date_from=adoption_from, date_to=adoption_to),
        "economy_metrics": pilot_economy_metrics(date_from=adoption_from, date_to=adoption_to),
        "recommendation_form": PilotRecommendationForm(), "pricing_hypothesis_form": PilotPricingHypothesisForm(),
        "organizations": Organization.objects.order_by("name"),
        "engineers": User.objects.filter(role=User.Role.ENGINEER).select_related("organization").order_by("organization__name", "username"),
        "project_statuses": Project.Status.choices, "onboarding_routes": ProjectOnboarding.Route.choices,
        "onboarding_statuses": ProjectOnboarding.Status.choices,
        "cities": Project.objects.exclude(location="").order_by("location").values_list("location", flat=True).distinct(),
        "project_totals": {"all": Project.objects.count(), "pending": Project.objects.filter(status=Project.Status.PENDING).count(), "ongoing": Project.objects.filter(status=Project.Status.ONGOING).count(), "complete": Project.objects.filter(status=Project.Status.COMPLETE).count()},
    })


def _pilot_review_parameters(request):
    try:
        horizon_days = int(request.GET.get("horizon", request.POST.get("horizon", 30)))
    except (TypeError, ValueError):
        horizon_days = 30
    if horizon_days not in PilotReviewDecision.Horizon.values:
        horizon_days = 30
    raw_date = request.GET.get("as_of", request.POST.get("as_of", ""))
    as_of_date = parse_date(raw_date) or timezone.localdate()
    return horizon_days, as_of_date


@require_GET
@superuser_required
def pilot_review(request):
    horizon_days, as_of_date = _pilot_review_parameters(request)
    snapshot = pilot_review_snapshot(horizon_days=horizon_days, as_of_date=as_of_date)
    return render(request, "superadmin/pilot/review.html", {
        "snapshot": snapshot,
        "horizons": PilotReviewDecision.Horizon.choices,
        "decision_form": PilotReviewDecisionForm(instance=snapshot["decision"]),
    })


@require_POST
@superuser_required
def pilot_review_decide(request):
    horizon_days, as_of_date = _pilot_review_parameters(request)
    existing = PilotReviewDecision.objects.filter(
        horizon_days=horizon_days, as_of_date=as_of_date
    ).first()
    form = PilotReviewDecisionForm(request.POST, instance=existing)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de la décision est obligatoire."))
    elif form.is_valid():
        decision = form.save(commit=False)
        decision.horizon_days = horizon_days
        decision.as_of_date = as_of_date
        decision.recorded_by = request.user
        decision.save()
        AuditEvent.objects.create(
            organization=None, actor=request.user, action="pilot.review_decided",
            target_type="pilot_review", target_id=str(decision.pk),
            metadata={
                "horizon_days": horizon_days, "as_of_date": as_of_date.isoformat(),
                "decision": decision.decision, "updated": existing is not None,
            },
        )
        messages.success(request, _("La décision go/no-go a été documentée et auditée."))
    else:
        messages.error(request, _("La décision est incomplète ou invalide."))
    return redirect(f"{reverse('superadmin:pilot-review')}?horizon={horizon_days}&as_of={as_of_date.isoformat()}")


@require_GET
@superuser_required
def pilot_review_export(request):
    horizon_days, as_of_date = _pilot_review_parameters(request)
    snapshot = pilot_review_snapshot(horizon_days=horizon_days, as_of_date=as_of_date)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="pivot-bilan-{horizon_days}j-{as_of_date.isoformat()}.csv"'
    )
    response.write("\ufeff")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(("Section", "Indicateur", "Valeur", "Définition"))
    rows = (
        ("Période", "Horizon", horizon_days, "Nombre de jours calendaires consolidés"),
        ("Période", "Début", snapshot["date_from"].isoformat(), "Début inclusif"),
        ("Période", "Fin", snapshot["date_to"].isoformat(), "Fin inclusive"),
        ("Adoption", "Projets activés", snapshot["adoption"]["active_projects"], "Activations confirmées"),
        ("Cohortes", "Route client", snapshot["adoption"]["routes"]["client_led"], "Onboardings initiés par un client"),
        ("Cohortes", "Route entrepreneur", snapshot["adoption"]["routes"]["contractor_led"], "Onboardings initiés par un entrepreneur"),
        ("Cohortes", "Route PIVOT", snapshot["adoption"]["routes"]["pivot_led"], "Onboardings concierge PIVOT"),
        ("Adoption", "Acceptation invitations (%)", snapshot["adoption"]["invitation_acceptance_rate"], "Acceptations sur invitations de la période"),
        ("Rétention", "Clients (%)", snapshot["economy"]["retention"]["client"]["rate"], "Proxy de reconnexion des clients affectés"),
        ("Rétention", "Entrepreneurs (%)", snapshot["economy"]["retention"]["contractor"]["rate"], "Proxy de reconnexion des entrepreneurs affectés"),
        ("Recommandation", "NPS", snapshot["economy"]["nps"] if snapshot["economy"]["nps"] is not None else "Non mesuré", "Promoteurs moins détracteurs"),
        ("Économie", "MRR XAF", snapshot["economy"]["mrr"], "Abonnements actifs, annuel divisé par douze"),
        ("Confiance", "Valeur suivie XAF", snapshot["trust"]["tracked_value"], "Budgets courants confirmés"),
        ("Confiance", "Dépenses vérifiées XAF", snapshot["trust"]["verified_expense_amount"], "Dépenses avec avis technique courant positif"),
        ("Qualité", "Anomalies", snapshot["trust"]["anomaly_count"], "Anomalies persistantes détectées dans la période"),
        ("Onboarding", "Frictions", snapshot["friction_count"], "Suivis concierge avec friction déclarée"),
    )
    writer.writerows(rows)
    if snapshot["decision"]:
        writer.writerow(("Décision", "Go/no-go", snapshot["decision"].get_decision_display(), "Décision documentée"))
        writer.writerow(("Décision", "Justification", snapshot["decision"].rationale, "Texte nécessaire à la décision"))
        writer.writerow(("Décision", "Décisions produit", snapshot["decision"].product_decisions, "Actions produit documentées"))
    AuditEvent.objects.create(
        organization=None, actor=request.user, action="pilot.review_exported",
        target_type="pilot_review_export", target_id=f"{horizon_days}-{as_of_date.isoformat()}",
        metadata={"horizon_days": horizon_days, "as_of_date": as_of_date.isoformat(), "pii": "minimized"},
    )
    return response


def _send_pivot_project_invitation(*, request, project, email, role):
    project_role = {
        User.Role.CLIENT: ProjectMembership.Role.OWNER,
        User.Role.CONTRACTOR: ProjectMembership.Role.CONTRACTOR,
        User.Role.ENGINEER: ProjectMembership.Role.ENGINEER,
        User.Role.SITE_MANAGER: ProjectMembership.Role.SITE_MANAGER,
    }[role]
    invitation, raw_token = create_invitation(
        actor=request.user, email=email, role=role, project=project, project_role=project_role
    )
    action_url = request.build_absolute_uri(
        reverse("accounts:accept-invitation", kwargs={"token": raw_token})
    )
    send_transactional_email(
        subject=f"Invitation au chantier {project.name}", recipient=invitation.email,
        text_template="emails/invitation.txt", html_template="emails/invitation.html",
        context={
            "organization_name": project.organization.name,
            "role_name": invitation.get_role_display(), "project_name": project.name,
            "action_url": action_url, "expiration_days": 7,
            "logo_url": request.build_absolute_uri(static("images/Logo.png")),
        },
    )
    AuditEvent.objects.create(
        organization=project.organization, actor=request.user,
        action="project.pivot_invitation_sent", target_type="Invitation",
        target_id=str(project.pk),
        metadata={
            "project_id": str(project.pk), "invitation_id": str(invitation.pk), "role": role
        },
    )
    return invitation


@superuser_required
def pivot_onboarding_create(request):
    form = PivotOnboardingForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            project = form.save(commit=False)
            project.engineer = None
            project.status = Project.Status.PENDING
            project.full_clean()
            project.save()
            onboarding = ProjectOnboarding.objects.create(
                organization=project.organization, project=project,
                route=ProjectOnboarding.Route.PIVOT_LED,
                financial_conditions=form.cleaned_data["financial_conditions"],
                initiated_by=request.user,
            )
            stage = ProjectStage(
                organization=project.organization, project=project,
                title=form.cleaned_data["stage_title"],
                start_date=form.cleaned_data["stage_start_date"],
                end_date=form.cleaned_data["stage_end_date"],
                estimated_cost=form.cleaned_data["stage_estimated_cost"],
                created_by=request.user,
            )
            stage.full_clean()
            stage.save()
            document = None
            if form.cleaned_data.get("document_file"):
                document = ProjectDocument.objects.create(
                    organization=project.organization, project=project,
                    title=form.cleaned_data["document_title"],
                    file=form.cleaned_data["document_file"], uploaded_by=request.user,
                )
            for action, target in [
                ("project.pivot_onboarding_created", project),
                ("project.pivot_stage_prepared", stage),
                *(([("project.pivot_document_prepared", document)]) if document else []),
            ]:
                AuditEvent.objects.create(
                    organization=project.organization, actor=request.user, action=action,
                    target_type=target.__class__.__name__, target_id=str(project.pk),
                    metadata={
                        "project_id": str(project.pk), "route": onboarding.route,
                        "prepared_target_id": str(target.pk),
                    },
                )
            if form.cleaned_data.get("owner_email"):
                _send_pivot_project_invitation(
                    request=request, project=project,
                    email=form.cleaned_data["owner_email"], role=User.Role.CLIENT,
                )
        messages.success(request, _("Le dossier concierge PIVOT a été préparé."))
        return redirect("superadmin:project-detail", pk=project.pk)
    return render(request, "superadmin/projects/onboarding_form.html", {"form": form})


@require_POST
@superuser_required
def pivot_project_invite(request, pk):
    project = get_object_or_404(
        Project, pk=pk, onboarding__route=ProjectOnboarding.Route.PIVOT_LED
    )
    form = PivotProjectInvitationForm(request.POST)
    if form.is_valid():
        try:
            _send_pivot_project_invitation(
                request=request, project=project,
                email=form.cleaned_data["email"], role=form.cleaned_data["role"],
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("L’invitation PIVOT a été envoyée."))
    else:
        messages.error(request, _("Invitation invalide."))
    return redirect("superadmin:project-detail", pk=project.pk)


@require_GET
@superuser_required
def project_detail(request, pk):
    project = get_object_or_404(Project.objects.select_related("organization", "engineer"), pk=pk)
    stages = list(project.stages.select_related("created_by").order_by("start_date"))
    progress = round(sum(stage.progress_percent for stage in stages) / len(stages)) if stages else 0
    successful_payments = project.payment_transactions.filter(
        status=PaymentTransaction.Status.SUCCESS
    )
    payment_totals = {
        row["currency"]: row["total"]
        for row in successful_payments.values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    }
    withdrawal_totals = {
        row["status"]: row["total"]
        for row in project.withdrawals.values("status")
        .annotate(total=Sum("amount"))
        .order_by("status")
    }
    concierge = concierge_checklist(project)
    return render(
        request,
        "superadmin/projects/detail.html",
        {
            "project": project,
            "onboarding": getattr(project, "onboarding", None),
            "concierge": concierge,
            "concierge_form": (
                ProjectConciergeFollowUpForm(instance=concierge["follow_up"], initial={
                    "pivot_agent": concierge["follow_up"].pivot_agent
                    if concierge["follow_up"] else request.user,
                }) if hasattr(project, "onboarding") else None
            ),
            "project_disputes": project.disputes.select_related(
                "raised_by", "resolved_by"
            ).prefetch_related("observations__author", "evidence_links__evidence"),
            "dispute_form": ProjectDisputeForm(project=project),
            "dispute_observation_form": ProjectDisputeObservationForm(),
            "dispute_resolution_form": ProjectDisputeResolutionForm(),
            "pivot_invitation_form": (
                PivotProjectInvitationForm()
                if hasattr(project, "onboarding")
                and project.onboarding.route == ProjectOnboarding.Route.PIVOT_LED
                else None
            ),
            "pivot_reviewer_form": PivotReviewerAssignmentForm(project=project),
            "pivot_reviewer": project.memberships.filter(
                project_role=ProjectMembership.Role.PIVOT_REVIEWER
            ).select_related("user").first(),
            "pivot_interventions": AuditEvent.objects.filter(
                target_id=str(project.pk), action__startswith="project.pivot_"
            ).select_related("actor")[:10],
            "onboarding_conflicts": project.onboarding_conflicts.select_related(
                "candidate_project", "resolved_by"
            ),
            "project_progress": progress,
            "stages": stages,
            "memberships": project.memberships.select_related("user").order_by(
                "project_role", "user__username"
            ),
            "project_counts": {
                "members": project.memberships.count(),
                "stages": len(stages),
                "stock": project.stock_items.count(),
                "documents": project.documents.count(),
                "pending_documents": project.documents.filter(
                    status=ProjectDocument.Status.VERIFIED
                ).count(),
                "photos": project.gallery_images.count(),
                "comments": project.comments.filter(is_deleted=False).count(),
            },
            "payment_totals": payment_totals,
            "withdrawal_totals": withdrawal_totals,
            "recent_status_history": project.status_history.select_related("actor")[:8],
            "intervention_form": ProjectInterventionForm(instance=project),
            "content_stages": project.stages.select_related("created_by").order_by("start_date"),
            "content_stock": project.stock_items.select_related("created_by").prefetch_related(
                "movements"
            ),
            "content_documents": project.documents.select_related("uploaded_by").order_by(
                "-uploaded_at"
            ),
            "content_photos": project.gallery_images.select_related("uploaded_by").order_by(
                "-created_at"
            ),
            "content_comments": project.comments.select_related("author").order_by("-created_at")[
                :20
            ],
            "content_withdrawals": project.withdrawals.select_related("requested_by").order_by(
                "-requested_at"
            ),
            "content_payments": project.payment_transactions.select_related("user").order_by(
                "-requested_at"
            )[:20],
        },
    )


@require_POST
@superuser_required
def project_pivot_reviewer_assign(request, pk):
    project = get_object_or_404(Project.objects.select_related("organization"), pk=pk)
    form = PivotReviewerAssignmentForm(request.POST, project=project)
    if request.POST.get("confirmed") != "yes" or not form.is_valid():
        messages.error(request, _("Sélectionnez un vérificateur PIVOT et confirmez l’affectation."))
        return redirect("superadmin:project-detail", pk=project.pk)

    reviewer = form.cleaned_data["reviewer"]
    with transaction.atomic():
        locked = Project.objects.select_for_update().get(pk=project.pk)
        previous_ids = list(
            locked.memberships.filter(
                project_role=ProjectMembership.Role.PIVOT_REVIEWER
            ).values_list("user_id", flat=True)
        )
        locked.memberships.filter(
            project_role=ProjectMembership.Role.PIVOT_REVIEWER
        ).exclude(user=reviewer).delete()
        ProjectMembership.objects.update_or_create(
            project=locked,
            user=reviewer,
            defaults={
                "organization": locked.organization,
                "project_role": ProjectMembership.Role.PIVOT_REVIEWER,
            },
        )
        AuditEvent.objects.create(
            organization=locked.organization,
            actor=request.user,
            action="project.pivot_reviewer_assigned",
            target_type="project",
            target_id=str(locked.pk),
            metadata={
                "reviewer_id": reviewer.pk,
                "previous_reviewer_ids": previous_ids,
            },
        )
    messages.success(request, f"{reviewer.get_username()} est maintenant vérificateur PIVOT du projet.")
    return redirect("superadmin:project-detail", pk=project.pk)


@require_POST
@superuser_required
def project_concierge_update(request, pk):
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de la mise à jour concierge est obligatoire."))
        return redirect("superadmin:project-detail", pk=pk)
    with transaction.atomic():
        project = get_object_or_404(
            Project.objects.select_for_update().select_related("organization", "onboarding"),
            pk=pk, onboarding__isnull=False,
        )
        existing = getattr(project.onboarding, "concierge_follow_up", None)
        form = ProjectConciergeFollowUpForm(request.POST, instance=existing)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("superadmin:project-detail", pk=pk)
        follow_up = form.save(commit=False)
        follow_up.onboarding = project.onboarding
        follow_up.organization = project.organization
        follow_up.updated_by = request.user
        follow_up.save()
        AuditEvent.objects.create(
            organization=project.organization, actor=request.user,
            action="project.pivot_concierge_updated", target_type="project",
            target_id=str(project.pk), metadata={
                "pivot_agent_id": follow_up.pivot_agent_id,
                "training_completed": follow_up.training_completed,
                "friction": follow_up.friction,
                "next_action": follow_up.next_action,
                "next_action_due_at": follow_up.next_action_due_at.isoformat()
                if follow_up.next_action_due_at else None,
                "onboarding_status": project.onboarding.status,
            },
        )
    messages.success(request, _("Le suivi concierge a été mis à jour et audité."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def project_dispute_open(request, pk):
    project = get_object_or_404(Project.objects.select_related("organization"), pk=pk)
    form = ProjectDisputeForm(request.POST, project=project)
    if request.POST.get("confirmed") == "yes" and form.is_valid():
        target_type, target_id = form.cleaned_data["target"].split(":", 1)
        try:
            open_dispute(
                actor=request.user, project=project, target_type=target_type,
                target_id=target_id, subject=form.cleaned_data["subject"],
                reason=form.cleaned_data["reason"],
                freezes_decision=form.cleaned_data["freezes_decision"],
                evidence=form.cleaned_data["evidence"],
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("La contestation a été ouverte et auditée."))
    else:
        messages.error(request, _("La contestation et sa confirmation sont invalides."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def project_dispute_observe(request, pk, dispute_pk):
    dispute = get_object_or_404(ProjectDispute, pk=dispute_pk, project_id=pk)
    form = ProjectDisputeObservationForm(request.POST)
    if form.is_valid():
        add_dispute_observation(actor=request.user, dispute=dispute, **form.cleaned_data)
        messages.success(request, _("L’observation contradictoire a été enregistrée."))
    else:
        messages.error(request, _("L’observation est invalide."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def project_dispute_resolve(request, pk, dispute_pk):
    dispute = get_object_or_404(ProjectDispute, pk=dispute_pk, project_id=pk)
    form = ProjectDisputeResolutionForm(request.POST)
    if request.POST.get("confirmed") == "yes" and form.is_valid():
        resolve_dispute(actor=request.user, dispute=dispute, **form.cleaned_data)
        messages.success(request, _("La contestation a été résolue sans supprimer les preuves."))
    else:
        messages.error(request, _("Une résolution motivée et confirmée est obligatoire."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def onboarding_conflict_resolve(request, pk, conflict_pk):
    if request.POST.get("confirmed") != "yes" or not request.POST.get("resolution_note", "").strip():
        messages.error(request, _("La confirmation et une note de résolution sont obligatoires."))
        return redirect("superadmin:project-detail", pk=pk)
    with transaction.atomic():
        review = get_object_or_404(
            OnboardingConflictReview.objects.select_for_update(),
            pk=conflict_pk, project_id=pk, status=OnboardingConflictReview.Status.OPEN,
        )
        review.status = OnboardingConflictReview.Status.RESOLVED
        review.resolved_at = timezone.now()
        review.resolved_by = request.user
        review.resolution_note = request.POST["resolution_note"].strip()
        review.save(update_fields=("status", "resolved_at", "resolved_by", "resolution_note"))
        AuditEvent.objects.create(
            organization=review.organization, actor=request.user,
            action="project.onboarding_conflict_resolved", target_type="project",
            target_id=str(pk),
            metadata={
                "candidate_project_id": str(review.candidate_project_id),
                "reason": review.reason, "note": review.resolution_note,
                "automatic_merge": False,
            },
        )
    messages.success(request, _("Le conflit a été examiné sans fusion automatique."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def project_intervene(request, pk):
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de l’intervention est obligatoire."))
        return redirect("superadmin:project-detail", pk=pk)

    with transaction.atomic():
        project = get_object_or_404(
            Project.objects.select_for_update().select_related("organization", "engineer"),
            pk=pk,
        )
        tracked_fields = (
            "name",
            "description",
            "location",
            "project_date",
            "budget_amount",
            "status",
        )
        previous = {field: getattr(project, field) for field in tracked_fields}
        previous["engineer_id"] = project.engineer_id
        previous_member_ids = set(project.memberships.values_list("user_id", flat=True))
        form = ProjectInterventionForm(request.POST, instance=project)
        if not form.is_valid():
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("superadmin:project-detail", pk=pk)

        updated = form.save(commit=False)
        updated.full_clean()
        new_members = list(form.cleaned_data["members"])
        selected_engineers = list(form.cleaned_data.get("engineers") or ())
        legacy_engineer = form.cleaned_data.get("engineer")
        if legacy_engineer and legacy_engineer not in selected_engineers:
            selected_engineers.append(legacy_engineer)
        new_members.extend(
            engineer for engineer in selected_engineers if engineer not in new_members
        )
        new_member_ids = {member.pk for member in new_members}
        changed_fields = [
            field for field in tracked_fields if previous[field] != getattr(updated, field)
        ]
        if previous["engineer_id"] != updated.engineer_id:
            changed_fields.append("engineer_id")
        if previous_member_ids != new_member_ids:
            changed_fields.append("members")
        if not changed_fields:
            messages.info(request, _("Aucun changement n’a été détecté."))
            return redirect("superadmin:project-detail", pk=pk)

        old_status = previous["status"]
        updated.save()
        if old_status != updated.status:
            ProjectStatusHistory.objects.create(
                project=updated,
                actor=request.user,
                previous_status=old_status,
                new_status=updated.status,
            )
        project.memberships.exclude(user_id__in=new_member_ids).delete()
        existing_ids = set(project.memberships.values_list("user_id", flat=True))
        for member in new_members:
            if member.pk not in existing_ids:
                membership = ProjectMembership(
                    organization=project.organization,
                    project=project,
                    user=member,
                    project_role={
                        User.Role.CLIENT: ProjectMembership.Role.OWNER,
                        User.Role.SITE_MANAGER: ProjectMembership.Role.SITE_MANAGER,
                        User.Role.ENGINEER: ProjectMembership.Role.ENGINEER,
                        User.Role.ADMIN: ProjectMembership.Role.PIVOT_REVIEWER,
                    }[member.role],
                )
                membership.full_clean()
                membership.save()

        def safe_value(field, value):
            if field == "project_date":
                return value.isoformat()
            if field == "budget_amount":
                return str(value)
            return value

        old_values = {
            field: safe_value(field, previous[field])
            for field in tracked_fields
            if field in changed_fields
        }
        new_values = {
            field: safe_value(field, getattr(updated, field))
            for field in tracked_fields
            if field in changed_fields
        }
        if "engineer_id" in changed_fields:
            old_values["engineer_id"] = previous["engineer_id"]
            new_values["engineer_id"] = updated.engineer_id
        if "members" in changed_fields:
            old_values["member_ids"] = sorted(previous_member_ids)
            new_values["member_ids"] = sorted(new_member_ids)
        AuditEvent.objects.create(
            organization=updated.organization,
            actor=request.user,
            action="project.intervened",
            target_type="project",
            target_id=str(updated.pk),
            metadata={
                "changed_fields": changed_fields,
                "previous": old_values,
                "new": new_values,
                "reason": form.cleaned_data["reason"],
            },
        )
        from apps.projects.access import project_engineers

        recipients = {*project_engineers(updated), *new_members}
        for recipient in recipients:
            create_notification(
                recipient=recipient,
                actor=request.user,
                kind=Notification.Kind.PROJECT,
                title="Intervention administrative sur le projet",
                message=(
                    f"Le projet « {updated.name} » a fait l’objet d’une correction exceptionnelle."
                ),
                target_url=reverse("projects:detail", kwargs={"pk": updated.pk}),
                project=updated,
            )
        messages.success(request, _("L’intervention exceptionnelle a été enregistrée et auditée."))
    return redirect("superadmin:project-detail", pk=pk)


@require_POST
@superuser_required
def project_content_action(request, pk, target_type, target_pk):
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation de l’intervention est obligatoire."))
        return redirect("superadmin:project-detail", pk=pk)
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.error(request, _("Le motif de l’intervention est obligatoire."))
        return redirect("superadmin:project-detail", pk=pk)
    action = request.POST.get("action", "")

    with transaction.atomic():
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk)
        model_map = {
            "stage": ProjectStage,
            "stock": StockItem,
            "document": ProjectDocument,
            "photo": ProjectImage,
            "comment": ProjectComment,
            "withdrawal": Withdrawal,
            "payment": PaymentTransaction,
        }
        model = model_map.get(target_type)
        if model is None:
            raise PermissionDenied
        target = get_object_or_404(
            model.objects.select_for_update(),
            pk=target_pk,
            project=project,
            organization=project.organization,
        )
        owner = None
        audit_action = ""
        metadata = {"operation": action, "reason": reason}

        if target_type == "stage" and action == "delete":
            if target.status != ProjectStage.Status.PENDING:
                messages.error(request, _("Seule une étape en attente peut être supprimée."))
                return redirect("superadmin:project-detail", pk=pk)
            owner, label = target.created_by, target.title
            target.delete()
            audit_action = "project_content.stage_deleted"
            metadata["label"] = label
        elif target_type == "stock" and action == "delete":
            if target.movements.exists():
                messages.error(
                    request,
                    _("Cet article possède un historique de mouvements et ne peut pas être supprimé."),
                )
                return redirect("superadmin:project-detail", pk=pk)
            owner, label = target.created_by, target.name
            target.delete()
            audit_action = "project_content.stock_deleted"
            metadata["label"] = label
        elif target_type == "document" and action in {"approve", "reject"}:
            if target.status != ProjectDocument.Status.VERIFIED:
                messages.error(request, _("Seul un document en attente peut être traité."))
                return redirect("superadmin:project-detail", pk=pk)
            decision = (
                ProjectDocument.Status.APPROVED
                if action == "approve"
                else ProjectDocument.Status.REJECTED
            )
            review_document(
                actor=request.user,
                document=target,
                decision=decision,
                reason=reason,
            )
            audit_action = "project_content.document_intervened"
            owner = None  # Le service de validation a déjà notifié le propriétaire.
        elif target_type == "photo" and action == "delete":
            owner, label = target.uploaded_by, target.caption
            target.delete()
            audit_action = "project_content.photo_deleted"
            metadata["label"] = label
        elif target_type == "comment" and action == "moderate":
            if target.is_deleted:
                messages.error(request, _("Ce commentaire est déjà supprimé."))
                return redirect("superadmin:project-detail", pk=pk)
            owner = target.author
            target.content = ""
            target.is_deleted = True
            target.deleted_by = request.user
            target.deleted_at = timezone.now()
            target.save(
                update_fields=("content", "is_deleted", "deleted_by", "deleted_at", "updated_at")
            )
            audit_action = "project_content.comment_moderated"
        elif target_type == "withdrawal" and action == "reject":
            if target.status != Withdrawal.Status.PENDING:
                messages.error(request, _("Seule une demande en attente peut être rejetée."))
                return redirect("superadmin:project-detail", pk=pk)
            decide_withdrawal(
                actor=request.user, withdrawal=target, status=Withdrawal.Status.REJECTED
            )
            audit_action = "project_content.withdrawal_intervened"
            owner = None  # Le service financier a déjà notifié le demandeur.
        elif target_type == "payment":
            messages.error(
                request,
                _("Une transaction de paiement est immuable et ne peut pas être modifiée ou supprimée."),
            )
            return redirect("superadmin:project-detail", pk=pk)
        else:
            messages.error(
                request, _("Cette action n’est pas autorisée pour l’état actuel du contenu.")
            )
            return redirect("superadmin:project-detail", pk=pk)

        AuditEvent.objects.create(
            organization=project.organization,
            actor=request.user,
            action=audit_action,
            target_type=target_type,
            target_id=str(target_pk),
            metadata=metadata,
        )
        if owner and owner.pk != request.user.pk:
            create_notification(
                recipient=owner,
                actor=request.user,
                kind=Notification.Kind.PROJECT,
                title="Intervention administrative sur un contenu",
                message=f"Une intervention a été effectuée sur le projet « {project.name} ».",
                target_url=reverse("projects:detail", kwargs={"pk": project.pk}),
                project=project,
            )
        messages.success(request, _("L’intervention sur le contenu a été confirmée et auditée."))
    return redirect("superadmin:project-detail", pk=pk)


@require_GET
@superuser_required
def project_content_preview(request, pk, target_type, target_pk):
    project = get_object_or_404(Project, pk=pk)
    if target_type == "document":
        target = get_object_or_404(
            ProjectDocument, pk=target_pk, project=project, organization=project.organization
        )
        stored_file = target.file
    elif target_type == "photo":
        target = get_object_or_404(
            ProjectImage, pk=target_pk, project=project, organization=project.organization
        )
        stored_file = target.image
    else:
        raise PermissionDenied
    filename = stored_file.name.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(stored_file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{filename.replace(chr(34), "")}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
@superuser_required
def validation_queue(request):
    selected_type = request.GET.get("type", "").strip()
    selected_organization = request.GET.get("organization", "").strip()
    selected_status = request.GET.get("status", "pending").strip()
    min_amount = request.GET.get("min_amount", "").strip()
    max_amount = request.GET.get("max_amount", "").strip()
    max_age = request.GET.get("age", "").strip()

    documents = ProjectDocument.objects.select_related(
        "organization", "project", "uploaded_by", "reviewed_by"
    )
    withdrawals = Withdrawal.objects.select_related(
        "organization", "project", "requested_by", "decided_by"
    )
    if selected_type == "document":
        withdrawals = withdrawals.none()
    elif selected_type == "withdrawal":
        documents = documents.none()
    elif selected_type:
        selected_type = ""
    if selected_organization.isdigit():
        organization_id = int(selected_organization)
        documents = documents.filter(organization_id=organization_id)
        withdrawals = withdrawals.filter(organization_id=organization_id)
    elif selected_organization:
        selected_organization = ""
    if selected_status not in {
        "pending",
        "verified",
        "approved",
        "rejected",
        "accounted",
        "all",
    }:
        selected_status = "pending"
    if selected_status == "pending":
        documents = documents.filter(status=ProjectDocument.Status.VERIFIED)
        withdrawals = withdrawals.filter(status=Withdrawal.Status.PENDING)
    elif selected_status != "all":
        documents = documents.filter(status=selected_status)
        withdrawals = withdrawals.filter(status=selected_status)
    if min_amount:
        try:
            withdrawals = withdrawals.filter(amount__gte=min_amount)
        except (ValueError, ValidationError):
            min_amount = ""
    if max_amount:
        try:
            withdrawals = withdrawals.filter(amount__lte=max_amount)
        except (ValueError, ValidationError):
            max_amount = ""
    if max_age.isdigit() and int(max_age) > 0:
        threshold = timezone.now() - timedelta(days=int(max_age))
        documents = documents.filter(uploaded_at__lte=threshold)
        withdrawals = withdrawals.filter(requested_at__lte=threshold)
    elif max_age:
        max_age = ""

    items = [
        {"kind": "document", "object": item, "date": item.uploaded_at, "amount": None}
        for item in documents
    ] + [
        {"kind": "withdrawal", "object": item, "date": item.requested_at, "amount": item.amount}
        for item in withdrawals
    ]
    items.sort(key=lambda item: item["date"], reverse=True)
    page = Paginator(items, 20).get_page(request.GET.get("page"))
    payment_totals = {
        row["currency"]: row["total"]
        for row in PaymentTransaction.objects.filter(status=PaymentTransaction.Status.SUCCESS)
        .values("currency")
        .annotate(total=Sum("amount"))
        .order_by("currency")
    }
    withdrawal_totals = {
        row["status"]: row["total"]
        for row in Withdrawal.objects.values("status")
        .annotate(total=Sum("amount"))
        .order_by("status")
    }
    return render(
        request,
        "superadmin/validations/queue.html",
        {
            "validation_page": page,
            "selected_type": selected_type,
            "selected_organization": selected_organization,
            "selected_status": selected_status,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "max_age": max_age,
            "organizations": Organization.objects.order_by("name"),
            "pending_document_count": ProjectDocument.objects.filter(
                status=ProjectDocument.Status.VERIFIED
            ).count(),
            "pending_withdrawal_count": Withdrawal.objects.filter(
                status=Withdrawal.Status.PENDING
            ).count(),
            "payment_totals": payment_totals,
            "withdrawal_totals": withdrawal_totals,
        },
    )


def _decision_reason(request):
    reason = request.POST.get("reason", "").strip()
    if not reason or len(reason) > 500:
        raise ValidationError(_("Un motif de 500 caractères maximum est obligatoire."))
    return reason


@require_GET
@superuser_required
def validation_document_preview(request, pk):
    document = get_object_or_404(ProjectDocument, pk=pk)
    previewed = set(request.session.get("superadmin_previewed_documents", []))
    previewed.add(str(document.pk))
    request.session["superadmin_previewed_documents"] = list(previewed)[-50:]
    filename = document.file.name.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(document.file.open("rb"), content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{filename.replace(chr(34), "")}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
@superuser_required
def validation_document_decide(request, pk):
    try:
        reason = _decision_reason(request)
        decision = request.POST.get("decision", "")
        previewed = set(request.session.get("superadmin_previewed_documents", []))
        if decision == ProjectDocument.Status.APPROVED and str(pk) not in previewed:
            raise ValidationError(_("Ouvrez l’aperçu du document avant de l’approuver."))
        with transaction.atomic():
            document = get_object_or_404(
                ProjectDocument.objects.select_for_update().select_related(
                    "project", "uploaded_by", "organization"
                ),
                pk=pk,
            )
            review_document(
                actor=request.user,
                document=document,
                decision=decision,
                reason=reason,
            )
            if str(pk) in previewed:
                previewed.remove(str(pk))
                request.session["superadmin_previewed_documents"] = list(previewed)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("La décision sur le document a été enregistrée."))
    return redirect("superadmin:validation-queue")


@require_POST
@superuser_required
def validation_withdrawal_decide(request, pk):
    decision = request.POST.get("decision", "")
    try:
        reason = _decision_reason(request)
        with transaction.atomic():
            withdrawal = get_object_or_404(
                Withdrawal.objects.select_for_update().select_related(
                    "project", "requested_by", "organization"
                ),
                pk=pk,
            )
            decide_withdrawal(actor=request.user, withdrawal=withdrawal, status=decision)
            AuditEvent.objects.filter(
                action="withdrawal.decided", target_id=str(withdrawal.pk)
            ).update(metadata={"status": decision, "reason": reason})
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, _("La décision sur le retrait a été enregistrée."))
    return redirect("superadmin:validation-queue")


SENSITIVE_AUDIT_KEYS = {
    "password",
    "password_hash",
    "token",
    "secret",
    "api_key",
    "authorization",
    "cookie",
    "file",
    "raw_response",
}


def _sanitized_metadata(value):
    if isinstance(value, dict):
        return {
            key: "[MASQUÉ]"
            if any(sensitive in key.lower() for sensitive in SENSITIVE_AUDIT_KEYS)
            else _sanitized_metadata(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitized_metadata(item) for item in value]
    return value


@require_GET
@superuser_required
def audit_event_list(request):
    events = AuditEvent.objects.select_related("actor", "organization")
    query = request.GET.get("q", "").strip()
    selected_actor = request.GET.get("actor", "").strip()
    selected_action = request.GET.get("action", "").strip()
    selected_organization = request.GET.get("organization", "").strip()
    selected_target_type = request.GET.get("target_type", "").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))
    if query:
        events = events.filter(
            Q(action__icontains=query)
            | Q(target_type__icontains=query)
            | Q(target_id__icontains=query)
            | Q(actor__username__icontains=query)
            | Q(organization__name__icontains=query)
        )
    if selected_actor.isdigit():
        events = events.filter(actor_id=int(selected_actor))
    elif selected_actor:
        selected_actor = ""
    available_actions = list(
        AuditEvent.objects.order_by("action").values_list("action", flat=True).distinct()
    )
    if selected_action in available_actions:
        events = events.filter(action=selected_action)
    elif selected_action:
        selected_action = ""
    if selected_organization == "platform":
        events = events.filter(organization__isnull=True)
    elif selected_organization.isdigit():
        events = events.filter(organization_id=int(selected_organization))
    elif selected_organization:
        selected_organization = ""
    available_target_types = list(
        AuditEvent.objects.order_by("target_type").values_list("target_type", flat=True).distinct()
    )
    if selected_target_type in available_target_types:
        events = events.filter(target_type=selected_target_type)
    elif selected_target_type:
        selected_target_type = ""
    if date_from:
        events = events.filter(created_at__date__gte=date_from)
    if date_to:
        events = events.filter(created_at__date__lte=date_to)
    page = Paginator(events.order_by("-created_at", "-pk"), 25).get_page(request.GET.get("page"))
    return render(
        request,
        "superadmin/audit/list.html",
        {
            "audit_page": page,
            "query": query,
            "selected_actor": selected_actor,
            "selected_action": selected_action,
            "selected_organization": selected_organization,
            "selected_target_type": selected_target_type,
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "actors": User.objects.filter(audit_events__isnull=False)
            .distinct()
            .order_by("username"),
            "organizations": Organization.objects.filter(audit_events__isnull=False)
            .distinct()
            .order_by("name"),
            "actions": available_actions,
            "target_types": available_target_types,
            "audit_total": AuditEvent.objects.count(),
        },
    )


@require_GET
@superuser_required
def audit_event_detail(request, pk):
    event = get_object_or_404(AuditEvent.objects.select_related("actor", "organization"), pk=pk)
    return render(
        request,
        "superadmin/audit/detail.html",
        {"event": event, "safe_metadata": _sanitized_metadata(event.metadata)},
    )


def _service_health():
    services = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        services.append(
            {"name": "Base de données", "status": "incident", "detail": "Connexion indisponible"}
        )
    else:
        engine = settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1]
        services.append(
            {"name": "Base de données", "status": "operational", "detail": engine.upper()}
        )

    email_backend = settings.EMAIL_BACKEND.rsplit(".", 1)[-1]
    services.append(
        {
            "name": "Service e-mail",
            "status": "warning" if "console" in email_backend.lower() else "operational",
            "detail": "Mode console (développement)"
            if "console" in email_backend.lower()
            else "Backend configuré",
        }
    )
    services.append(
        {
            "name": "Stockage des fichiers",
            "status": "operational",
            "detail": "Stockage Django configuré",
        }
    )
    services.append(
        {
            "name": "Sécurité applicative",
            "status": "warning" if settings.DEBUG else "operational",
            "detail": "Mode développement" if settings.DEBUG else "Mode production",
        }
    )
    return services


@superuser_required
def platform_settings(request):
    configuration = PlatformConfiguration.load()
    tracked_fields = PlatformConfigurationForm._meta.fields
    previous = {field: getattr(configuration, field) for field in tracked_fields}
    form = PlatformConfigurationForm(request.POST or None, instance=configuration)
    if request.method == "POST":
        if request.POST.get("confirmed") != "yes":
            messages.error(request, _("La confirmation de modification est obligatoire."))
        elif form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            current = {field: getattr(updated, field) for field in tracked_fields}
            changed_fields = [
                field for field in tracked_fields if previous[field] != current[field]
            ]
            if changed_fields:
                AuditEvent.objects.create(
                    actor=request.user,
                    action="platform.settings_updated",
                    target_type="platform_configuration",
                    target_id=str(updated.pk),
                    metadata={"changed_fields": changed_fields},
                )
            messages.success(request, _("Les paramètres de la plateforme ont été enregistrés."))
            return redirect("superadmin:settings")
    gateway_name = os.environ.get("PAYMENT_GATEWAY", settings.PAYMENT_GATEWAY).lower()
    mesomb_keys_present = all(
        (
            os.environ.get("MESOMB_APPLICATION_KEY")
            or os.environ.get("MESOMB_APP_KEY")
            or settings.MESOMB_APPLICATION_KEY,
            os.environ.get("MESOMB_ACCESS_KEY") or settings.MESOMB_ACCESS_KEY,
            os.environ.get("MESOMB_SECRET_KEY") or settings.MESOMB_SECRET_KEY,
        )
    )
    integrations = [
        {
            "name": "Passerelle de paiement",
            "provider": "MeSomb" if gateway_name == "mesomb" else "Simulateur local",
            "status": "operational"
            if gateway_name != "mesomb" or mesomb_keys_present
            else "incident",
            "credential": "••••••••"
            if gateway_name == "mesomb" and mesomb_keys_present
            else "Non applicable",
        },
        {
            "name": "E-mail transactionnel",
            "provider": settings.EMAIL_BACKEND.rsplit(".", 1)[-1],
            "status": "warning" if "console" in settings.EMAIL_BACKEND.lower() else "operational",
            "credential": "••••••••"
            if hasattr(settings, "EMAIL_HOST_PASSWORD") and settings.EMAIL_HOST_PASSWORD
            else "Non configuré",
        },
    ]
    return render(
        request,
        "superadmin/settings.html",
        {
            "form": form,
            "configuration": configuration,
            "services": _service_health(),
            "integrations": integrations,
            "last_settings_event": AuditEvent.objects.filter(action="platform.settings_updated")
            .select_related("actor")
            .first(),
        },
    )


@require_GET
@superuser_required
def subscription_list(request):
    subscriptions = OrganizationSubscription.objects.select_related("organization", "plan")
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    plan_id = request.GET.get("plan", "").strip()
    due_before = parse_date(request.GET.get("due_before", ""))
    usage_level = request.GET.get("usage", "").strip()
    if query:
        subscriptions = subscriptions.filter(Q(organization__name__icontains=query) | Q(organization__slug__icontains=query))
    if status in OrganizationSubscription.Status.values:
        subscriptions = subscriptions.filter(status=status)
    if plan_id:
        subscriptions = subscriptions.filter(plan_id=plan_id)
    if due_before:
        subscriptions = subscriptions.filter(current_period_ends_at__date__lte=due_before)
    rows = []
    for subscription in subscriptions.order_by("current_period_ends_at", "organization__name"):
        usage = quota_usage(subscription.organization)
        subscription.usage = usage
        subscription.usage_level = "limit" if usage["projects"].reached or usage["members"].reached else "warning" if usage["projects"].warning or usage["members"].warning else "normal"
        if usage_level and subscription.usage_level != usage_level:
            continue
        rows.append(subscription)
    return render(request, "superadmin/subscriptions/list.html", {
        "subscription_page": Paginator(rows, 20).get_page(request.GET.get("page")),
        "plans": SubscriptionPlan.objects.all().order_by("display_order", "name"),
        "statuses": OrganizationSubscription.Status.choices,
        "query": query, "selected_status": status, "selected_plan": plan_id,
        "selected_usage": usage_level, "due_before": request.GET.get("due_before", ""),
        "plan_form": SubscriptionPlanForm(), "intervention_form": SubscriptionInterventionForm(),
    })


@require_POST
@superuser_required
def subscription_plan_create(request):
    form = SubscriptionPlanForm(request.POST)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation est obligatoire."))
    elif form.is_valid():
        plan = form.save()
        AuditEvent.objects.create(actor=request.user, action="subscription_plan.created", target_type="subscription_plan", target_id=str(plan.pk), metadata={"code": plan.code})
        messages.success(request, _("Le forfait a été créé."))
    else:
        messages.error(request, _(" ").join(error for values in form.errors.values() for error in values))
    return redirect("superadmin:subscription-list")


@require_POST
@superuser_required
def subscription_plan_update(request, pk):
    plan = get_object_or_404(SubscriptionPlan, pk=pk)
    form = SubscriptionPlanForm(request.POST, instance=plan)
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation est obligatoire."))
    elif form.is_valid():
        before = plan.snapshot()
        plan = form.save()
        AuditEvent.objects.create(actor=request.user, action="subscription_plan.updated", target_type="subscription_plan", target_id=str(plan.pk), metadata={"previous": before, "current": plan.snapshot()})
        messages.success(request, _("Le forfait a été modifié sans altérer les contrats existants."))
    else:
        messages.error(request, _(" ").join(error for values in form.errors.values() for error in values))
    return redirect("superadmin:subscription-list")


@require_POST
@superuser_required
def subscription_intervene(request, pk):
    form = SubscriptionInterventionForm(request.POST)
    if request.POST.get("confirmed") != "yes" or not form.is_valid():
        errors = " ".join(error for values in form.errors.values() for error in values)
        messages.error(request, errors or "La confirmation et le motif sont obligatoires.")
        return redirect("superadmin:subscription-list")
    with transaction.atomic():
        subscription = get_object_or_404(OrganizationSubscription.objects.select_for_update().select_related("plan", "organization"), pk=pk)
        if form.cleaned_data["expected_updated_at"] != subscription.updated_at.isoformat():
            messages.error(request, _("L’abonnement a changé depuis l’ouverture de la modale. Rechargez la page."))
            return redirect("superadmin:subscription-list")
        before = {"status": subscription.status, "plan": subscription.plan.code, "start": subscription.current_period_started_at.isoformat() if subscription.current_period_started_at else None, "end": subscription.current_period_ends_at.isoformat() if subscription.current_period_ends_at else None}
        action = form.cleaned_data["action"]
        now = timezone.now()
        if action == "extend":
            start = subscription.current_period_ends_at if subscription.current_period_ends_at and subscription.current_period_ends_at > now else now
            subscription.current_period_started_at = subscription.current_period_started_at or now
            subscription.current_period_ends_at = start + timedelta(days=form.cleaned_data["extension_days"])
            subscription.status = OrganizationSubscription.Status.ACTIVE
            subscription.grace_ends_at = None
        elif action == "change_plan":
            subscription.plan = form.cleaned_data["plan"]
            subscription.plan_snapshot = subscription.plan.snapshot()
        elif action == "suspend":
            subscription.status = OrganizationSubscription.Status.SUSPENDED
        elif action == "reactivate":
            subscription.status = OrganizationSubscription.Status.ACTIVE
            subscription.current_period_started_at = subscription.current_period_started_at or now
            subscription.current_period_ends_at = subscription.current_period_ends_at if subscription.current_period_ends_at and subscription.current_period_ends_at > now else add_calendar_months(now, 1)
            subscription.grace_ends_at = None
        subscription.save()
        metadata = {"action": action, "reason": form.cleaned_data["reason"].strip(), "previous": before}
        SubscriptionEvent.objects.create(subscription=subscription, actor=request.user, event_type=f"subscription.admin_{action}", previous_status=before["status"], new_status=subscription.status, plan_snapshot=subscription.plan_snapshot, metadata=metadata)
        AuditEvent.objects.create(organization=subscription.organization, actor=request.user, action=f"subscription.admin_{action}", target_type="organization_subscription", target_id=str(subscription.pk), metadata=metadata)
    messages.success(request, _("L’intervention sur l’abonnement a été appliquée et auditée."))
    return redirect("superadmin:subscription-list")
