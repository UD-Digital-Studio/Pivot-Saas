from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import FormView, TemplateView

from .forms import (
    ClientRegistrationForm,
    EngineerRegistrationForm,
    InvitationAcceptanceForm,
    MemberInvitationForm,
    UserAccountForm,
    UserProfileForm,
)
from .models import Invitation, Notification, User, UserProfile
from .services import (
    accept_invitation_for_existing_user,
    create_invitation,
    hash_invitation_token,
    send_transactional_email,
)


class EngineerRegistrationView(FormView):
    template_name = "accounts/engineer_registration.html"
    form_class = EngineerRegistrationForm
    success_url = reverse_lazy("accounts:registration-pending")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:post-login")
        from apps.audit.models import PlatformConfiguration

        if not PlatformConfiguration.load().engineer_registration_enabled:
            messages.error(request, _("Les inscriptions ingénieur sont temporairement fermées."))
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        engineer = form.save()
        login_url = self.request.build_absolute_uri(reverse("accounts:login"))
        logo_url = self.request.build_absolute_uri(static("images/Logo.png"))
        send_transactional_email(
            subject="Votre demande d’inscription PIVOT a été reçue",
            recipient=engineer.email,
            text_template="emails/engineer_registration_received.txt",
            html_template="emails/engineer_registration_received.html",
            context={"user": engineer, "login_url": login_url, "logo_url": logo_url},
        )
        validation_url = self.request.build_absolute_uri(
            reverse("superadmin:user-detail", kwargs={"pk": engineer.pk})
        )
        validators = User.objects.filter(is_superuser=True, is_active=True).exclude(email="")
        for validator in validators:
            send_transactional_email(
                subject="Nouvelle demande ingénieur à valider",
                recipient=validator.email,
                text_template="emails/engineer_validation_pending.txt",
                html_template="emails/engineer_validation_pending.html",
                context={
                    "validator": validator,
                    "engineer": engineer,
                    "organization": engineer.organization,
                    "action_url": validation_url,
                    "logo_url": logo_url,
                },
            )
        return super().form_valid(form)


class ClientRegistrationView(FormView):
    template_name = "accounts/client_registration.html"
    form_class = ClientRegistrationForm
    success_url = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("accounts:post-login")
        from apps.audit.models import PlatformConfiguration

        if not PlatformConfiguration.load().client_registration_enabled:
            messages.error(request, _("Les inscriptions client sont temporairement fermées."))
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Votre compte client est créé. Vous pouvez vous connecter.")
        return super().form_valid(form)


class RegistrationPendingView(TemplateView):
    template_name = "accounts/registration_pending.html"


@login_required
def invite_member(request):
    if request.user.role not in {User.Role.ENGINEER, User.Role.ADMIN}:
        raise PermissionDenied

    form = MemberInvitationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            invitation, raw_token = create_invitation(
                actor=request.user,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
            )
        except ValidationError as exc:
            form.add_error("email", exc.message)
        else:
            acceptance_url = request.build_absolute_uri(
                reverse("accounts:accept-invitation", kwargs={"token": raw_token})
            )
            send_transactional_email(
                subject="Invitation à rejoindre PIVOT-SASS",
                recipient=invitation.email,
                text_template="emails/invitation.txt",
                html_template="emails/invitation.html",
                context={
                    "organization_name": invitation.organization.name,
                    "role_name": invitation.get_role_display(),
                    "action_url": acceptance_url,
                    "expiration_days": 7,
                    "logo_url": request.build_absolute_uri(static("images/Logo.png")),
                },
            )
            messages.success(request, _("L'invitation a été envoyée."))
            return redirect("accounts:dashboard", role=request.user.role)

    request._invitation_form = form
    request._open_invitation_modal = True
    return dashboard.__wrapped__(request, role=request.user.role)


def accept_invitation(request, token):
    invitation = get_object_or_404(Invitation, token_hash=hash_invitation_token(token))
    if not invitation.is_usable:
        raise Http404

    existing_user = User.objects.filter(email__iexact=invitation.email).first()
    if existing_user:
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:login')}?next={request.path}")
        if request.user.pk != existing_user.pk:
            raise PermissionDenied("Cette invitation est destinée à un autre compte.")
        if request.method == "POST":
            try:
                accept_invitation_for_existing_user(invitation=invitation, user=request.user)
            except (PermissionDenied, ValidationError) as error:
                messages.error(request, str(error))
            else:
                messages.success(request, _("Vous avez rejoint le chantier."))
                if invitation.project_id:
                    return redirect(invitation.project.get_absolute_url())
                return redirect("accounts:post-login")
        return render(
            request, "accounts/accept_invitation.html",
            {"form": None, "invitation": invitation, "existing_account": True},
        )

    form = InvitationAcceptanceForm(request.POST or None, invitation=invitation)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Votre compte est actif. Vous pouvez maintenant vous connecter."))
        return redirect("accounts:login")
    return render(
        request,
        "accounts/accept_invitation.html",
        {"form": form, "invitation": invitation},
    )


@require_POST
@login_required
def cancel_invitation(request, pk):
    if request.user.role not in {User.Role.ENGINEER, User.Role.ADMIN}:
        raise PermissionDenied
    invitation = get_object_or_404(
        Invitation,
        pk=pk,
        organization_id=request.user.organization_id,
    )
    if request.POST.get("confirmed") != "yes":
        messages.error(request, _("La confirmation est obligatoire pour annuler l’invitation."))
    elif not invitation.is_usable:
        messages.info(request, _("Cette invitation n’est plus active."))
    else:
        invitation.canceled_at = timezone.now()
        invitation.save(update_fields=("canceled_at",))
        messages.success(request, f"L’invitation envoyée à {invitation.email} a été annulée.")
    return redirect("accounts:dashboard", role=request.user.role)


@login_required
def profile(request):
    user_profile, profile_created = UserProfile.objects.get_or_create(user=request.user)
    account_form = UserAccountForm(request.POST or None, instance=request.user)
    profile_form = UserProfileForm(
        request.POST or None,
        request.FILES or None,
        instance=user_profile,
    )
    if request.method == "POST" and account_form.is_valid() and profile_form.is_valid():
        with transaction.atomic():
            account_form.save()
            profile_form.save()
        messages.success(request, _("Votre profil a été mis à jour."))
        return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"account_form": account_form, "profile_form": profile_form},
    )


@require_GET
@login_required
def post_login(request):
    if request.user.is_superuser:
        return redirect("superadmin:dashboard")
    return redirect("accounts:dashboard", role=request.user.role)


@require_GET
@login_required
def notification_center(request):
    notifications = request.user.notifications.select_related("actor")
    selected = request.GET.get("filter", "all")
    if selected == "unread":
        notifications = notifications.filter(is_read=False)
    elif selected != "all":
        selected = "all"
    page = Paginator(notifications, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/notifications.html",
        {"notification_page": page, "notification_filter": selected},
    )


@require_POST
@login_required
def notification_read(request, pk):
    notification = get_object_or_404(
        Notification,
        pk=pk,
        recipient=request.user,
    )
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=("is_read", "read_at"))
    if notification.target_url.startswith("/") and not notification.target_url.startswith("//"):
        return redirect(notification.target_url)
    return redirect("accounts:notifications")


@require_POST
@login_required
def notifications_read_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    return redirect("accounts:notifications")


@require_GET
@login_required
def dashboard(request, role):
    if role != request.user.role or role not in User.Role.values:
        raise Http404
    from apps.projects.forms import ProjectCreateForm
    from apps.projects.models import Project
    from apps.projects.selectors import projects_for_user
    from apps.subscriptions.quotas import quota_usage

    projects = projects_for_user(request.user)
    subscription_usage = quota_usage(request.user.organization)
    total_projects = projects.count()
    ongoing_projects = projects.filter(status=Project.Status.ONGOING).count()
    complete_projects = projects.filter(status=Project.Status.COMPLETE).count()
    pending_projects = projects.filter(status=Project.Status.PENDING).count()
    project_stats = {
        "total": total_projects,
        "ongoing": ongoing_projects,
        "complete": complete_projects,
        "pending": pending_projects,
        "budget": projects.aggregate(total=Sum("budget_amount"))["total"] or 0,
    }
    project_chart = {
        "ongoing_percent": round(ongoing_projects * 100 / total_projects) if total_projects else 0,
        "complete_percent": round(complete_projects * 100 / total_projects)
        if total_projects
        else 0,
        "pending_percent": round(pending_projects * 100 / total_projects) if total_projects else 0,
    }
    query = request.GET.get("q", "").strip()
    selected_status = request.GET.get("status", "").strip()
    filtered_projects = projects
    if query:
        filtered_projects = filtered_projects.filter(
            Q(name__icontains=query) | Q(location__icontains=query)
        )
    if selected_status in Project.Status.values:
        filtered_projects = filtered_projects.filter(status=selected_status)
    elif selected_status:
        selected_status = ""
    recent_projects = Paginator(filtered_projects.order_by("-updated_at"), 5).get_page(
        request.GET.get("page")
    )
    can_invite = request.user.organization_id is not None and request.user.role in {
        request.user.Role.ENGINEER,
        request.user.Role.ADMIN,
    }
    pending_invitations = Invitation.objects.none()
    invitation_history = Invitation.objects.none()
    if can_invite:
        organization_invitations = Invitation.objects.filter(
            organization_id=request.user.organization_id,
        ).select_related("invited_by", "project")
        pending_invitations = organization_invitations.active().order_by("expires_at")[:10]
        invitation_history = organization_invitations.closed().order_by("-created_at")[:20]

    role_metric = {"kind": "budget", "value": project_stats["budget"]}
    if request.user.role == User.Role.CLIENT:
        from apps.finance.models import PaymentTransaction

        role_metric = {
            "kind": "paid",
            "value": PaymentTransaction.objects.filter(
                project__in=projects,
                user=request.user,
                status=PaymentTransaction.Status.SUCCESS,
            ).aggregate(total=Sum("amount"))["total"]
            or 0,
        }
    elif request.user.role == User.Role.SITE_MANAGER:
        from apps.planning.models import ProjectStage

        role_metric = {
            "kind": "active_stages",
            "value": ProjectStage.objects.filter(
                project__in=projects, status=ProjectStage.Status.ACTIVE
            ).count(),
        }
    return render(
        request,
        "accounts/dashboard.html",
        {
            "role_label": request.user.get_role_display(),
            "project_stats": project_stats,
            "project_chart": project_chart,
            "recent_projects": recent_projects,
            "dashboard_query": query,
            "selected_status": selected_status,
            "project_statuses": Project.Status.choices,
            "role_metric": role_metric,
            "project_form": ProjectCreateForm(organization=request.user.organization),
            "invitation_form": getattr(request, "_invitation_form", MemberInvitationForm()),
            "open_invitation_modal": getattr(request, "_open_invitation_modal", False),
            "can_invite": can_invite,
            "pending_invitations": pending_invitations,
            "invitation_history": invitation_history,
            "subscription_usage": subscription_usage,
            "can_create_project": request.user.role == User.Role.ENGINEER
            and not subscription_usage["projects"].reached,
        },
    )
