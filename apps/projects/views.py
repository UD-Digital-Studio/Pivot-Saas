from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils.translation import gettext_lazy as _
from django.templatetags.static import static
from django.urls import reverse

from apps.accounts.services import create_invitation, send_transactional_email

from apps.collaboration.forms import CommentForm, DocumentForm, DocumentReviewForm, EvidenceCaptureForm, EvidenceCorrectionForm, ImageForm
from apps.collaboration.models import EvidenceRecord, ProjectDocument
from apps.collaboration.services import can_access_evidence, can_capture_evidence, can_correct_evidence, can_read_document, can_view_evidence_location
from apps.audit.models import PlatformConfiguration
from apps.finance.forms import ExpenseAttachmentDecisionForm, ExpenseAttachmentForm, ExpenseOwnerDecisionForm, ExpensePaymentForm, ExpensePivotVerificationForm, ExpenseRequestForm, ExpenseTechnicalOpinionForm, PaymentForm, WithdrawalForm
from apps.finance.models import ExpenseRequestAttachment
from apps.finance.services import allowed_expense_transitions, can_create_expense_request, evaluate_expense_risk, expense_dossier_inconsistencies, financial_totals, missing_expense_documents
from apps.inventory.forms import (
    ExpectedRangeAssignmentForm, InventoryAnomalyDecisionForm,
    InventoryAnomalyResolutionForm, StockAdjustmentForm, StockImportForm, StockItemForm,
)
from apps.inventory.services import (
    can_adjust_stock, can_configure_expected_ranges, can_propose_anomaly_resolution,
    can_validate_anomaly_resolution,
)
from apps.planning.forms import ProjectStageForm, StageProgressDeclarationForm, StageProgressVerificationForm, StageTechnicalReviewForm, StageSiteVisitForm, StageSiteVerificationForm, StageInspectionRiskRuleForm
from apps.planning.services import can_manage_stages

from .forms import (
    ClientLedProjectForm,
    ContractorLedProjectForm,
    ContractorOnboardingConfirmationForm,
    OwnershipConfirmationForm,
    ProjectActorInvitationForm,
    ProjectCreateForm,
    ProjectForm,
    ProjectMembersForm,
    ProjectOwnerChangeForm,
    ProjectStatusForm,
    ProjectTermsRevisionForm,
)
from .models import Project, ProjectMembership, ProjectOnboarding, ProjectOwnership
from .access import PROJECT_TECHNICAL_ROLES, can_authorize_project_finance, has_project_role, project_role_for
from .selectors import projects_for_user
from .controlled_value import controlled_value_indicators
from .services import (
    activate_client_led_project,
    available_status_transitions,
    can_manage_project,
    client_led_onboarding_missing,
    change_project_status,
    change_project_owner,
    confirm_project_ownership,
    confirm_contractor_led_onboarding,
    create_terms_version,
    record_actor_confirmation,
    ensure_can_create_project,
    project_has_confirmed_owner,
    project_finance_is_unlocked,
)


@require_GET
@login_required
def member_search(request):
    if request.user.organization_id is None or request.user.role not in {
        request.user.Role.ENGINEER,
        request.user.Role.ADMIN,
    }:
        raise PermissionDenied
    query = request.GET.get("q", "").strip()
    if len(query) < 2:
        return JsonResponse({"results": []})
    users = (
        request.user.__class__.objects.filter(
            organization=request.user.organization,
            role__in=(request.user.Role.CLIENT, request.user.Role.SITE_MANAGER),
            is_active=True,
        )
        .filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
        .order_by("role", "first_name", "last_name", "username")[:10]
    )
    return JsonResponse(
        {
            "results": [
                {
                    "id": str(user.pk),
                    "label": user.get_full_name() or user.get_username(),
                    "username": user.get_username(),
                    "role": user.get_role_display(),
                }
                for user in users
            ]
        }
    )


@login_required
def project_list(request):
    from apps.subscriptions.quotas import quota_usage

    subscription_usage = quota_usage(request.user.organization)
    queryset = projects_for_user(request.user)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(location__icontains=query))
    if status in Project.Status.values:
        queryset = queryset.filter(status=status)
    sort = request.GET.get("sort", "updated_desc")
    sort_fields = {
        "updated_desc": ("-updated_at",),
        "updated_asc": ("updated_at",),
        "name_asc": ("name",),
        "name_desc": ("-name",),
        "date_desc": ("-project_date",),
        "budget_desc": ("-budget_amount",),
    }
    if sort not in sort_fields:
        sort = "updated_desc"
    queryset = queryset.order_by(*sort_fields[sort])
    page = Paginator(queryset, 12).get_page(request.GET.get("page"))
    return render(
        request,
        "projects/project_list.html",
        {
            "page": page,
            "query": query,
            "selected_status": status,
            "selected_sort": sort,
            "statuses": Project.Status,
            "can_create": request.user.organization_id is not None
            and request.user.role in {
                request.user.Role.ENGINEER, request.user.Role.CLIENT, request.user.Role.CONTRACTOR
            }
            and not subscription_usage["projects"].reached,
            "subscription_usage": subscription_usage,
            "project_form": (
                ClientLedProjectForm()
                if request.user.role == request.user.Role.CLIENT
                else ContractorLedProjectForm()
                if request.user.role == request.user.Role.CONTRACTOR
                else ProjectCreateForm(organization=request.user.organization)
            ),
        },
    )


@login_required
def project_create(request):
    try:
        ensure_can_create_project(request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("projects:list")
    client_led = request.user.role == request.user.Role.CLIENT
    contractor_led = request.user.role == request.user.Role.CONTRACTOR
    if client_led:
        form = ClientLedProjectForm(request.POST or None, request.FILES or None)
    elif contractor_led:
        form = ContractorLedProjectForm(request.POST or None, request.FILES or None)
    else:
        form = ProjectCreateForm(
            request.POST or None,
            request.FILES or None,
            organization=request.user.organization,
        )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            project = form.save(commit=False)
            project.organization = request.user.organization
            project.engineer = None if (client_led or contractor_led) else request.user
            project.full_clean()
            project.save()
            ProjectMembership.objects.update_or_create(
                project=project,
                user=request.user,
                defaults={
                    "organization": project.organization,
                    "project_role": (
                        ProjectMembership.Role.OWNER
                        if client_led
                        else ProjectMembership.Role.CONTRACTOR
                        if contractor_led
                        else ProjectMembership.Role.ENGINEER
                    ),
                },
            )
            if client_led:
                ProjectOwnership.objects.create(
                    organization=project.organization,
                    project=project,
                    owner=request.user,
                )
                ProjectOnboarding.objects.create(
                    organization=project.organization,
                    project=project,
                    route=ProjectOnboarding.Route.CLIENT_LED,
                    financial_conditions=form.cleaned_data["financial_conditions"],
                    initiated_by=request.user,
                )
            elif contractor_led:
                ProjectOnboarding.objects.create(
                    organization=project.organization,
                    project=project,
                    route=ProjectOnboarding.Route.CONTRACTOR_LED,
                    financial_conditions=form.cleaned_data["financial_conditions"],
                    initiated_by=request.user,
                )
            else:
                form.save_members(project)
        messages.success(request, _("Le projet a été créé."))
        return redirect("projects:detail", pk=project.pk)
    return render(request, "projects/project_form.html", {"form": form, "mode": "create"})


@login_required
def project_detail(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    tabs = (
        ("overview", _("Vue d’ensemble")),
        ("stages", _("Étapes et vérifications")),
        ("expenses", _("Dépenses")),
        ("finance", _("Finances")),
        ("stock", _("Stock")),
        ("documents", _("Documents")),
        ("photos", _("Photos")),
        ("comments", _("Commentaires")),
        ("evidence", _("Preuves terrain")),
        ("reports", _("Rapports")),
    )
    selected_tab = request.GET.get("tab", "overview")
    tab_labels = dict(tabs)
    if selected_tab not in tab_labels:
        selected_tab = "overview"
    current_project_role = project_role_for(user=request.user, project=project)
    is_assigned_manager = current_project_role == ProjectMembership.Role.SITE_MANAGER
    is_assigned_client = current_project_role == ProjectMembership.Role.OWNER
    ownership_is_valid = project_has_confirmed_owner(project)
    try:
        onboarding = project.onboarding
    except ProjectOnboarding.DoesNotExist:
        onboarding = None
    onboarding_missing = client_led_onboarding_missing(project) if onboarding else ()
    is_preliminary_contractor = bool(
        onboarding
        and onboarding.route == ProjectOnboarding.Route.CONTRACTOR_LED
        and onboarding.status != ProjectOnboarding.Status.ACTIVE
        and current_project_role == ProjectMembership.Role.CONTRACTOR
    )
    can_manage = can_manage_project(actor=request.user, project=project)
    user_can_manage_stages = can_manage_stages(actor=request.user, project=project)
    user_can_adjust_stock = can_adjust_stock(actor=request.user, project=project)
    user_can_configure_ranges = can_configure_expected_ranges(actor=request.user, project=project)
    stages = list(project.stages.select_related("created_by").prefetch_related(
        "progress_declarations__author", "progress_declarations__evidence",
        "progress_declarations__technical_review__reviewer",
        "progress_declarations__digital_verification__initiated_by",
        "progress_verifications__author", "progress_verifications__evidence",
        "progress_verifications__declaration", "progress_verifications__digital_verification",
        "site_visits__inspector", "site_visits__verification__inspector",
        "site_visits__verification__evidence",
    ))
    if stages:
        project_progress = round(sum(stage.progress_percent for stage in stages) / len(stages))
    else:
        project_progress = {
            Project.Status.PENDING: 0,
            Project.Status.ONGOING: 50,
            Project.Status.COMPLETE: 100,
        }[project.status]
    if user_can_manage_stages:
        for stage in stages:
            stage.edit_form = ProjectStageForm(instance=stage)
    can_verify_stage_progress = (
        request.user.is_superuser
        or has_project_role(
            user=request.user,
            project=project,
            roles={ProjectMembership.Role.ENGINEER},
        )
    )
    can_run_digital_verification = has_project_role(
        user=request.user, project=project, roles=PROJECT_TECHNICAL_ROLES
    )
    can_run_site_verification = request.user.is_superuser or has_project_role(
        user=request.user, project=project, roles={ProjectMembership.Role.PIVOT_REVIEWER}
    )
    for stage in stages:
        stage.declaration_form = StageProgressDeclarationForm(stage=stage) if user_can_manage_stages else None
        latest_declaration = stage.latest_declared_progress
        digital_verification = (
            getattr(latest_declaration, "digital_verification", None)
            if latest_declaration
            else None
        )
        stage.verification_form = (
            StageProgressVerificationForm(stage=stage)
            if can_verify_stage_progress
            and latest_declaration
            and digital_verification
            and digital_verification.result == digital_verification.Result.PASSED
            and not hasattr(latest_declaration, "technical_verification")
            else None
        )
        stage.pending_review_declaration = (
            latest_declaration
            if can_verify_stage_progress and latest_declaration and not hasattr(latest_declaration, "technical_review")
            else None
        )
        stage.technical_review_form = StageTechnicalReviewForm() if stage.pending_review_declaration else None
        stage.pending_digital_declaration = (
            latest_declaration
            if can_run_digital_verification
            and latest_declaration
            and hasattr(latest_declaration, "technical_review")
            and latest_declaration.technical_review.decision != "rejected"
            and not hasattr(latest_declaration, "digital_verification")
            else None
        )
        stage.site_visit_form = StageSiteVisitForm() if can_run_site_verification else None
        latest_visit = stage.site_visits.order_by("-visited_at").first()
        stage.pending_site_visit = (
            latest_visit
            if can_run_site_verification and latest_visit
            and not hasattr(latest_visit, "verification")
            and stage.latest_verified_progress
            else None
        )
        stage.site_verification_form = (
            StageSiteVerificationForm(stage=stage) if stage.pending_site_visit else None
        )
        technical = stage.latest_verified_progress
        stage.risk_assessment = getattr(technical, "risk_assessment", None) if technical else None
        stage.can_evaluate_risk = bool(can_run_digital_verification and technical and not stage.risk_assessment)
    declared_values = [s.declared_progress_percent for s in stages if s.declared_progress_percent is not None]
    verified_values = [s.verified_progress_percent for s in stages if s.verified_progress_percent is not None]
    declared_project_progress = round(sum(declared_values) / len(declared_values)) if declared_values else None
    verified_project_progress = round(sum(verified_values) / len(verified_values)) if verified_values else None
    stock_items = list(project.stock_items.select_related("created_by", "verified_by", "expected_range"))
    if user_can_adjust_stock:
        for item in stock_items:
            item.adjustment_form = StockAdjustmentForm(project=project)
    if user_can_configure_ranges:
        for item in stock_items:
            item.expected_range_form = ExpectedRangeAssignmentForm(project=project, item=item)
    stock_movements = project.stock_movements.select_related("item", "actor", "evidence", "stage")
    stock_date_from = request.GET.get("date_from", "")
    stock_date_to = request.GET.get("date_to", "")
    if stock_date_from:
        stock_movements = stock_movements.filter(created_at__date__gte=stock_date_from)
    if stock_date_to:
        stock_movements = stock_movements.filter(created_at__date__lte=stock_date_to)
    stock_history_page = Paginator(stock_movements, 10).get_page(request.GET.get("stock_page"))
    documents = project.documents.select_related("uploaded_by", "reviewed_by")
    evidence_records = list(project.evidence_records.select_related("author", "stage", "document", "image").prefetch_related("next_versions"))
    evidence_policy = PlatformConfiguration.load()
    for evidence in evidence_records:
        evidence.can_download = can_access_evidence(actor=request.user, evidence=evidence, action="download")
    user_can_correct_evidence = can_correct_evidence(actor=request.user, project=project)
    if user_can_correct_evidence:
        for evidence in evidence_records:
            if evidence.status in {EvidenceRecord.Status.VERIFIED, EvidenceRecord.Status.APPROVED} and not evidence.next_versions.all():
                evidence.correction_form = EvidenceCorrectionForm(project=project, original=evidence)
    can_verify_documents = has_project_role(
        user=request.user, project=project, roles=PROJECT_TECHNICAL_ROLES
    )
    visible_document_count = documents.count()
    document_query = request.GET.get("document_q", "").strip()
    document_status = request.GET.get("document_status", "").strip()
    document_sort = request.GET.get("document_sort", "uploaded_desc")
    if document_query:
        documents = documents.filter(
            Q(title__icontains=document_query)
            | Q(uploaded_by__username__icontains=document_query)
        )
    if document_status in ProjectDocument.Status.values:
        documents = documents.filter(status=document_status)
    elif document_status:
        document_status = ""
    document_sort_fields = {
        "uploaded_desc": ("-uploaded_at",),
        "uploaded_asc": ("uploaded_at",),
        "title_asc": ("title",),
        "status_asc": ("status", "title"),
    }
    if document_sort not in document_sort_fields:
        document_sort = "uploaded_desc"
    documents = documents.order_by(*document_sort_fields[document_sort])
    gallery_images = project.gallery_images.select_related("uploaded_by")
    project_comments = project.comments.select_related("author", "deleted_by")
    comment_page = Paginator(project_comments, 10).get_page(request.GET.get("comment_page"))
    collaboration_counts = {
        "documents": visible_document_count,
        "photos": gallery_images.count(),
        "comments": project_comments.filter(is_deleted=False).count(),
    }
    financial_transactions = Paginator(
        project.payment_transactions.select_related("user"), 10
    ).get_page(request.GET.get("finance_page"))
    withdrawals = Paginator(
        project.withdrawals.select_related("requested_by", "decided_by"), 10
    ).get_page(request.GET.get("withdrawal_page"))
    expense_requests = list(project.expense_requests.select_related("author", "milestone").prefetch_related(
        "attachments__evidence", "attachments__replaced_by__evidence",
        "technical_opinions__engineer", "pivot_verifications__reviewer",
        "owner_decisions__owner", "payment_transactions", "transitions__actor",
        "inventory_anomalies__item", "inventory_anomalies__expected_range",
    ))
    for expense_request in expense_requests:
        expense_request.allowed_transitions = allowed_expense_transitions(actor=request.user, expense_request=expense_request)
        expense_request.missing_documents = sorted(missing_expense_documents(expense_request))
        expense_request.dossier_complete = not expense_request.missing_documents
        expense_request.can_manage_dossier = request.user.is_superuser or (
            request.user.pk == expense_request.author_id
            and expense_request.status in {"draft", "submitted", "evidence", "review", "verified"}
        )
        expense_request.attachment_form = ExpenseAttachmentForm(project=project)
        expense_request.can_submit_technical_opinion = (
            expense_request.status == "review"
            and (
                request.user.is_superuser
                or has_project_role(
                    user=request.user, project=project,
                    roles={ProjectMembership.Role.ENGINEER},
                )
            )
        )
        expense_request.technical_opinion_form = ExpenseTechnicalOpinionForm(
            initial={"expected_version": expense_request.status_version}
        )
        risk = evaluate_expense_risk(expense_request, persist=False)
        expense_request.display_risk_score = risk["score"]
        expense_request.display_risk_level = risk["level"]
        expense_request.display_risk_required = risk["required"]
        expense_request.display_risk_reasons = risk["reasons"]
        expense_request.dossier_inconsistencies = expense_dossier_inconsistencies(expense_request)
        expense_request.can_submit_pivot_verification = (
            expense_request.status == "verified"
            and risk["required"]
            and (
                request.user.is_superuser
                or has_project_role(
                    user=request.user, project=project,
                    roles={ProjectMembership.Role.PIVOT_REVIEWER},
                )
            )
        )
        expense_request.pivot_verification_form = ExpensePivotVerificationForm(
            allow_exceptional=request.user.is_superuser,
            initial={"expected_version": expense_request.status_version},
        )
        expense_request.can_owner_decide = (
            expense_request.status == "verified"
            and is_assigned_client
            and ownership_is_valid
        )
        expense_request.owner_approve_form = ExpenseOwnerDecisionForm(initial={
            "decision": "approved", "expected_version": expense_request.status_version,
        })
        expense_request.owner_reject_form = ExpenseOwnerDecisionForm(initial={
            "decision": "rejected", "expected_version": expense_request.status_version,
        })
        expense_request.can_execute_payment = (
            expense_request.status == "authorized"
            and is_assigned_client and ownership_is_valid
            and project_finance_is_unlocked(project)
            and not expense_request.payment_transactions.filter(status__in={"pending", "success"}).exists()
        )
        expense_request.expense_payment_form = ExpensePaymentForm()
        for anomaly in expense_request.inventory_anomalies.all():
            has_pending_resolution = anomaly.resolutions.filter(status="pending").exists()
            anomaly.resolution_form = (
                InventoryAnomalyResolutionForm(project=project)
                if can_propose_anomaly_resolution(actor=request.user, anomaly=anomaly)
                and not has_pending_resolution else None
            )
            anomaly.resolution_history = list(anomaly.resolutions.select_related(
                "responsible", "proposed_by", "decided_by"
            ).prefetch_related("evidence"))
            for resolution in anomaly.resolution_history:
                resolution.can_decide = (
                    resolution.status == "pending"
                    and can_validate_anomaly_resolution(actor=request.user, anomaly=anomaly)
                )
                resolution.decision_form = InventoryAnomalyDecisionForm()
        for attachment in expense_request.attachments.all():
            attachment.can_replace = expense_request.can_manage_dossier and attachment.status in {
                ExpenseRequestAttachment.Status.ACTIVE,
                ExpenseRequestAttachment.Status.REJECTED,
            }
            attachment.can_reject = can_verify_documents and attachment.status == ExpenseRequestAttachment.Status.ACTIVE
            attachment.replacement_form = ExpenseAttachmentDecisionForm(project=project, replacement_required=True)
    transitions = available_status_transitions(actor=request.user, project=project)
    status_choices = [choice for choice in Project.Status.choices if choice[0] in transitions]
    recent_activity = []
    for change in project.status_history.select_related("actor")[:8]:
        recent_activity.append(
            {
                "date": change.created_at,
                "label": f"Statut : {change.get_previous_status_display()} → {change.get_new_status_display()}",
                "actor": change.actor,
                "tab": "overview",
            }
        )
    for stage in sorted(stages, key=lambda item: item.updated_at, reverse=True)[:8]:
        recent_activity.append(
            {
                "date": stage.updated_at,
                "label": f"Étape : {stage.title} · {stage.get_status_display()}",
                "actor": stage.created_by,
                "tab": "stages",
            }
        )
    recent_activity = sorted(recent_activity, key=lambda item: item["date"], reverse=True)[:8]
    controlled_value = controlled_value_indicators(actor=request.user, project=project)
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "ownership": getattr(project, "ownership", None),
            "ownership_is_valid": ownership_is_valid,
            "onboarding": onboarding,
            "project_is_preliminary": bool(
                onboarding and onboarding.status != ProjectOnboarding.Status.ACTIVE
            ),
            "onboarding_missing": onboarding_missing,
            "onboarding_progress": max(0, 100 - (len(onboarding_missing) * 25)),
            "can_activate_onboarding": bool(
                onboarding
                and can_authorize_project_finance(user=request.user, project=project)
                and not onboarding_missing
            ),
            "actor_invitation_form": (
                ProjectActorInvitationForm(
                    allowed_roles=(
                        {request.user.Role.CLIENT}
                        if is_preliminary_contractor
                        else {
                            request.user.Role.CONTRACTOR,
                            request.user.Role.SITE_MANAGER,
                            request.user.Role.ENGINEER,
                        }
                    )
                )
                if (
                    can_authorize_project_finance(user=request.user, project=project)
                    or can_manage
                    or is_preliminary_contractor
                )
                else None
            ),
            "is_preliminary_contractor": is_preliminary_contractor,
            "contractor_confirmation_form": (
                ContractorOnboardingConfirmationForm()
                if onboarding
                and onboarding.route in {
                    ProjectOnboarding.Route.CONTRACTOR_LED,
                    ProjectOnboarding.Route.PIVOT_LED,
                }
                and is_assigned_client
                and not ownership_is_valid
                else None
            ),
            "current_terms": project.terms_versions.filter(is_current=True).first(),
            "my_actor_confirmation": project.actor_confirmations.filter(
                user=request.user, terms_version__is_current=True
            ).first(),
            "terms_revision_form": (
                ProjectTermsRevisionForm(
                    initial={
                        "budget_amount": project.budget_amount,
                        "currency": project.terms_versions.filter(is_current=True).values_list("currency", flat=True).first() or "XAF",
                        "financial_conditions": onboarding.financial_conditions if onboarding else "",
                        "targeted_roles": ["contractor", "engineer"],
                    }
                ) if onboarding and can_authorize_project_finance(user=request.user, project=project) else None
            ),
            "can_confirm_ownership": is_assigned_client
            and not ownership_is_valid
            and not (
                onboarding and onboarding.route in {
                    ProjectOnboarding.Route.CONTRACTOR_LED,
                    ProjectOnboarding.Route.PIVOT_LED,
                }
            ),
            "ownership_confirmation_form": OwnershipConfirmationForm(),
            "owner_change_form": ProjectOwnerChangeForm(project=project) if can_manage else None,
            "can_manage": can_manage,
            "memberships": project.memberships.select_related("user"),
            "tabs": tabs,
            "selected_tab": selected_tab,
            "selected_tab_label": tab_labels[selected_tab],
            "can_pay": is_assigned_client and ownership_is_valid and project_finance_is_unlocked(project),
            "can_manage_stages": user_can_manage_stages,
            "can_verify_stage_progress": can_verify_stage_progress,
            "can_run_digital_verification": can_run_digital_verification,
            "can_run_site_verification": can_run_site_verification,
            "inspection_risk_rule": project.organization.inspection_risk_rules.filter(is_active=True).first(),
            "inspection_risk_rule_form": StageInspectionRiskRuleForm() if request.user.is_superuser else None,
            "stages": stages,
            "stage_form": ProjectStageForm() if user_can_manage_stages else None,
            "can_adjust_stock": user_can_adjust_stock,
            "can_configure_expected_ranges": user_can_configure_ranges,
            "can_verify_stock": has_project_role(
                user=request.user, project=project, roles=PROJECT_TECHNICAL_ROLES
            ),
            "stock_items": stock_items,
            "stock_item_form": StockItemForm() if user_can_adjust_stock else None,
            "stock_import_form": StockImportForm() if user_can_adjust_stock else None,
            "stock_history_page": stock_history_page,
            "stock_date_from": stock_date_from,
            "stock_date_to": stock_date_to,
            "documents": documents,
            "evidence_records": evidence_records,
            "can_capture_evidence": can_capture_evidence(actor=request.user, project=project),
            "can_view_evidence_location": can_view_evidence_location(actor=request.user, project=project),
            "can_correct_evidence": user_can_correct_evidence,
            "can_review_evidence": has_project_role(user=request.user, project=project, roles=PROJECT_TECHNICAL_ROLES),
            "evidence_form": EvidenceCaptureForm(project=project),
            "document_query": document_query,
            "document_status": document_status,
            "document_sort": document_sort,
            "document_statuses": ProjectDocument.Status.choices,
            "document_form": DocumentForm(),
            "document_review_form": DocumentReviewForm(),
            "can_verify_documents": can_verify_documents,
            "gallery_images": gallery_images,
            "image_form": ImageForm(),
            "project_comments": comment_page,
            "comment_page": comment_page,
            "collaboration_counts": collaboration_counts,
            "comment_form": CommentForm(),
            "financial_totals": financial_totals(project),
            "payment_form": PaymentForm() if is_assigned_client and ownership_is_valid and project_finance_is_unlocked(project) else None,
            "withdrawal_form": WithdrawalForm() if can_manage else None,
            "financial_transactions": financial_transactions,
            "withdrawals": withdrawals,
            "expense_requests": expense_requests,
            "can_create_expense_request": can_create_expense_request(actor=request.user, project=project),
            "expense_request_form": ExpenseRequestForm(project=project),
            "can_collaborate": can_manage or is_assigned_client or is_assigned_manager,
            "edit_form": ProjectForm(instance=project),
            "members_form": ProjectMembersForm(project=project) if can_manage else None,
            "status_form": ProjectStatusForm(choices=status_choices) if status_choices else None,
            "status_history": project.status_history.select_related("actor")[:10],
            "project_progress": project_progress,
            "declared_project_progress": declared_project_progress,
            "verified_project_progress": verified_project_progress,
            "recent_activity": recent_activity,
            "controlled_value": controlled_value,
        },
    )


@login_required
def project_members(request, pk):
    project = get_object_or_404(
        projects_for_user(request.user).select_related("organization", "engineer"), pk=pk
    )
    if not can_manage_project(actor=request.user, project=project):
        raise PermissionDenied
    form = ProjectMembersForm(
        request.POST if request.method == "POST" else None,
        project=project,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Les affectations du projet ont été mises à jour."))
        return redirect("projects:detail", pk=project.pk)
    return render(request, "projects/project_members.html", {"project": project, "form": form})


@require_POST
@login_required
def project_ownership_confirm(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    form = OwnershipConfirmationForm(request.POST)
    if form.is_valid():
        try:
            ownership, created = confirm_project_ownership(
                actor=request.user,
                project=project,
                terms_accepted=form.cleaned_data["terms_accepted"],
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _("Votre qualité de propriétaire a été confirmée.")
                if created
                else "Votre qualité de propriétaire était déjà confirmée.",
            )
    else:
        messages.error(request, _("Vous devez accepter les conditions avant de confirmer."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def project_owner_change(request, pk):
    project = get_object_or_404(
        projects_for_user(request.user).select_related("organization"), pk=pk
    )
    form = ProjectOwnerChangeForm(request.POST, project=project)
    if form.is_valid():
        try:
            change_project_owner(
                actor=request.user,
                project=project,
                new_owner=form.cleaned_data["new_owner"],
                reason=form.cleaned_data["reason"],
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _("Le nouveau propriétaire doit maintenant confirmer son ownership."),
            )
    else:
        messages.error(request, _("Le propriétaire et le motif sont obligatoires."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def project_actor_invite(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    current_role = project_role_for(user=request.user, project=project)
    form = ProjectActorInvitationForm(
        request.POST,
        allowed_roles=(
            {request.user.Role.CLIENT}
            if current_role == ProjectMembership.Role.CONTRACTOR
            else {
                request.user.Role.CONTRACTOR,
                request.user.Role.SITE_MANAGER,
                request.user.Role.ENGINEER,
            }
        ),
    )
    if form.is_valid():
        role = form.cleaned_data["role"]
        project_role = {
            request.user.Role.CLIENT: ProjectMembership.Role.OWNER,
            request.user.Role.CONTRACTOR: ProjectMembership.Role.CONTRACTOR,
            request.user.Role.SITE_MANAGER: ProjectMembership.Role.SITE_MANAGER,
            request.user.Role.ENGINEER: ProjectMembership.Role.ENGINEER,
        }[role]
        try:
            invitation, raw_token = create_invitation(
                actor=request.user, email=form.cleaned_data["email"], role=role,
                project=project, project_role=project_role,
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            acceptance_url = request.build_absolute_uri(
                reverse("accounts:accept-invitation", kwargs={"token": raw_token})
            )
            send_transactional_email(
                subject=f"Invitation au chantier {project.name}",
                recipient=invitation.email,
                text_template="emails/invitation.txt",
                html_template="emails/invitation.html",
                context={
                    "organization_name": invitation.organization.name,
                    "role_name": invitation.get_role_display(),
                    "project_name": project.name,
                    "action_url": acceptance_url,
                    "expiration_days": 7,
                    "logo_url": request.build_absolute_uri(static("images/Logo.png")),
                },
            )
            messages.success(request, _("L’intervenant a été invité au chantier."))
    else:
        messages.error(request, _("Vérifiez l’adresse e-mail et le rôle sélectionné."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def contractor_onboarding_confirm(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    form = ContractorOnboardingConfirmationForm(request.POST)
    if form.is_valid():
        try:
            confirm_contractor_led_onboarding(
                actor=request.user, project=project, confirmations=form.cleaned_data
            )
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, _("Le projet, les acteurs et les conditions sont confirmés."))
    else:
        messages.error(request, _("Toutes les confirmations sont obligatoires."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def actor_confirmation_respond(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    role = project_role_for(user=request.user, project=project)
    if role not in {ProjectMembership.Role.CONTRACTOR, ProjectMembership.Role.ENGINEER}:
        raise PermissionDenied
    accepted = request.POST.get("decision") == "accept"
    try:
        record_actor_confirmation(
            user=request.user, project=project, project_role=role, accepted=accepted
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Participation acceptée.") if accepted else "Participation refusée.")
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def project_terms_revise(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    if not can_authorize_project_finance(user=request.user, project=project):
        raise PermissionDenied
    form = ProjectTermsRevisionForm(request.POST)
    if form.is_valid():
        create_terms_version(actor=request.user, project=project, **form.cleaned_data)
        messages.success(request, _("Une nouvelle version des conditions exige désormais les confirmations ciblées."))
    else:
        messages.error(request, _("La nouvelle version des conditions est invalide."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@require_POST
@login_required
def project_onboarding_activate(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    try:
        activate_client_led_project(actor=request.user, project=project)
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Le chantier est maintenant actif."))
    return redirect(f"{project.get_absolute_url()}?tab=overview")


@login_required
def project_update(request, pk):
    project = get_object_or_404(
        projects_for_user(request.user).select_related("organization", "engineer"), pk=pk
    )
    if not can_manage_project(actor=request.user, project=project):
        raise PermissionDenied
    form = ProjectForm(request.POST or None, request.FILES or None, instance=project)
    if request.method == "POST" and form.is_valid():
        updated_project = form.save(commit=False)
        updated_project.organization = project.organization
        updated_project.engineer = project.engineer
        updated_project.full_clean()
        updated_project.save()
        messages.success(request, _("Le projet a été mis à jour."))
        return redirect("projects:detail", pk=project.pk)
    return render(
        request,
        "projects/project_form.html",
        {"form": form, "mode": "update", "project": project},
    )


@login_required
def project_status_update(request, pk):
    project = get_object_or_404(
        projects_for_user(request.user).select_related("organization", "engineer"), pk=pk
    )
    if not can_manage_project(actor=request.user, project=project):
        raise PermissionDenied
    choices = [
        choice
        for choice in Project.Status.choices
        if choice[0] in available_status_transitions(actor=request.user, project=project)
    ]
    if request.method != "POST":
        raise PermissionDenied
    form = ProjectStatusForm(request.POST, choices=choices)
    if form.is_valid():
        change_project_status(
            actor=request.user, project=project, new_status=form.cleaned_data["status"]
        )
        messages.success(request, _("Le statut du projet a été mis à jour."))
    else:
        messages.error(request, _("Le changement de statut demandé est invalide."))
    return redirect("projects:detail", pk=project.pk)
