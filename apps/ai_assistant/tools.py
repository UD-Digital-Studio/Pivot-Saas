import json
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from apps.accounts.models import User
from apps.collaboration.models import ProjectDocument
from apps.finance.models import PaymentTransaction
from apps.finance.services import financial_totals
from apps.organizations.models import Organization
from apps.subscriptions.models import OrganizationSubscription
from apps.subscriptions.quotas import quota_usage
from apps.projects.access import project_role_for
from apps.projects.models import ProjectMembership

from .policy import SAFE_DENIAL, accessible_projects, capabilities_for_user
from .routing import detect_intents

MAX_PROJECTS = 10
MAX_ITEMS_PER_TOOL = 20
MAX_COMMENT_CHARS = 500


class ToolPermissionDenied(Exception):
    pass


@dataclass(frozen=True)
class ToolResult:
    name: str
    data: dict


def _text(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _progress(project):
    stages = list(project.stages.all())
    if stages:
        return round(sum(stage.progress_percent for stage in stages) / len(stages))
    return {"pending": 0, "ongoing": 50, "complete": 100}.get(project.status, 0)


def _selected_projects(user, question):
    projects = list(
        accessible_projects(user).prefetch_related("stages").order_by("name")[:MAX_PROJECTS]
    )
    normalized = str(question or "").casefold()
    named = [project for project in projects if project.name.casefold() in normalized]
    if named:
        return named
    if len(projects) == 1:
        return projects
    return projects


def detect_tool_intent(question):
    intents = detect_intents(question)
    return intents[0] if intents else None


def project_tool(user, projects):
    from apps.projects.access import project_engineers

    project_rows = []
    for project in projects:
        engineers = [
            engineer.get_full_name() or engineer.get_username()
            for engineer in project_engineers(project)
        ]
        project_rows.append(
            {
                "name": project.name,
                "location": project.location,
                "date": _text(project.project_date),
                "status": project.status,
                "status_label": project.get_status_display(),
                "budget_xaf": _text(project.budget_amount),
                "progress_percent": _progress(project),
                "engineer": ", ".join(engineers),
                "engineers": engineers,
            }
        )
    return ToolResult(
        "projects.read",
        {
            "count": len(projects),
            "projects": project_rows,
        },
    )


def platform_tool(user, projects, question=""):
    normalized = str(question or "").casefold()
    asks_global_scope = any(
        term in normalized
        for term in (
            "plateforme",
            "platform",
            "toutes les organisations",
            "all organizations",
            "combien d'organisation",
            "combien d’organisation",
            "nombre d'organisation",
            "nombre d’organisation",
        )
    )
    if user.is_superuser:
        organizations = Organization.objects.all().order_by("name")
    elif asks_global_scope or not user.organization_id:
        raise ToolPermissionDenied(SAFE_DENIAL)
    else:
        organizations = Organization.objects.filter(pk=user.organization_id)
    return ToolResult(
        "platform.statistics",
        {
            "scope": "platform" if user.is_superuser else "current_organization",
            "organization_count": organizations.count(),
            "active_organization_count": organizations.filter(
                status=Organization.Status.ACTIVE
            ).count(),
            "suspended_organization_count": organizations.filter(
                status=Organization.Status.SUSPENDED
            ).count(),
            "archived_organization_count": organizations.filter(
                status=Organization.Status.ARCHIVED
            ).count(),
            "organizations": [
                {
                    "name": organization.name,
                    "status": organization.status,
                    "status_label": organization.get_status_display(),
                }
                for organization in organizations[:MAX_ITEMS_PER_TOOL]
            ],
        },
    )


def user_directory_tool(user, question=""):
    if not (user.is_superuser or user.role == User.Role.ADMIN):
        raise ToolPermissionDenied(SAFE_DENIAL)

    normalized = str(question or "").casefold()
    organizations = Organization.objects.all()
    mentioned = [
        organization for organization in organizations if organization.name.casefold() in normalized
    ]
    if user.is_superuser:
        selected_organizations = mentioned or list(organizations.order_by("name"))
    else:
        if mentioned and any(organization.pk != user.organization_id for organization in mentioned):
            raise ToolPermissionDenied(SAFE_DENIAL)
        selected_organizations = [user.organization]

    organization_ids = [organization.pk for organization in selected_organizations]
    users = (
        User.objects.filter(organization_id__in=organization_ids)
        .select_related("organization")
        .order_by("organization__name", "username")[:MAX_ITEMS_PER_TOOL]
    )
    return ToolResult(
        "users.directory",
        {
            "scope": "platform" if user.is_superuser else "current_organization",
            "organization_count": len(selected_organizations),
            "user_count": User.objects.filter(organization_id__in=organization_ids).count(),
            "results_limited_to": MAX_ITEMS_PER_TOOL,
            "users": [
                {
                    "organization": item.organization.name,
                    "name": item.get_full_name() or item.get_username(),
                    "username": item.get_username(),
                    "role": item.role,
                    "role_label": item.get_role_display(),
                    "is_active": item.is_active,
                }
                for item in users
            ],
        },
    )


def stage_tool(user, projects):
    rows = []
    for project in projects:
        for stage in project.stages.order_by("start_date")[:MAX_ITEMS_PER_TOOL]:
            rows.append(
                {
                    "project": project.name,
                    "title": stage.title,
                    "start_date": _text(stage.start_date),
                    "end_date": _text(stage.end_date),
                    "status": stage.status,
                    "status_label": stage.get_status_display(),
                    "progress_percent": stage.progress_percent,
                    "is_overdue": stage.is_overdue,
                    "estimated_cost_xaf": _text(stage.estimated_cost),
                    "actual_cost_xaf": _text(stage.actual_cost),
                }
            )
            if len(rows) >= MAX_ITEMS_PER_TOOL:
                break
        if len(rows) >= MAX_ITEMS_PER_TOOL:
            break
    return ToolResult("stages.read", {"count": len(rows), "stages": rows})


def stock_tool(user, projects):
    rows = []
    for project in projects:
        for item in project.stock_items.order_by("name")[:MAX_ITEMS_PER_TOOL]:
            rows.append(
                {
                    "project": project.name,
                    "name": item.name,
                    "unit": item.unit,
                    "quantity": _text(item.quantity),
                    "alert_threshold": _text(item.alert_threshold),
                    "is_low_stock": item.is_low_stock,
                    "unit_price_xaf": _text(item.unit_price),
                    "total_value_xaf": _text(item.total_price),
                    "status": item.status,
                    "status_label": item.get_status_display(),
                }
            )
            if len(rows) >= MAX_ITEMS_PER_TOOL:
                break
        if len(rows) >= MAX_ITEMS_PER_TOOL:
            break
    return ToolResult("stock.read", {"count": len(rows), "items": rows})


def document_tool(user, projects):
    can_review = "document.review" in capabilities_for_user(user)
    rows = []
    for project in projects:
        documents = project.documents.order_by("-uploaded_at")
        if not can_review:
            documents = documents.filter(status=ProjectDocument.Status.APPROVED)
        for document in documents[:MAX_ITEMS_PER_TOOL]:
            rows.append(
                {
                    "project": project.name,
                    "title": document.title,
                    "status": document.status,
                    "status_label": document.get_status_display(),
                    "uploaded_at": _text(document.uploaded_at),
                    "reviewed_at": _text(document.reviewed_at),
                }
            )
            if len(rows) >= MAX_ITEMS_PER_TOOL:
                break
        if len(rows) >= MAX_ITEMS_PER_TOOL:
            break
    return ToolResult("documents.read", {"count": len(rows), "documents": rows})


def photo_tool(user, projects):
    rows = []
    for project in projects:
        for photo in project.gallery_images.order_by("-created_at")[:MAX_ITEMS_PER_TOOL]:
            rows.append(
                {
                    "project": project.name,
                    "caption": photo.caption or "",
                    "is_cover": photo.is_cover,
                    "created_at": _text(photo.created_at),
                }
            )
            if len(rows) >= MAX_ITEMS_PER_TOOL:
                break
        if len(rows) >= MAX_ITEMS_PER_TOOL:
            break
    return ToolResult("photos.read", {"count": len(rows), "photos": rows})


def comment_tool(user, projects):
    rows = []
    for project in projects:
        comments = project.comments.filter(is_deleted=False).select_related("author")
        for comment in comments.order_by("-created_at")[:MAX_ITEMS_PER_TOOL]:
            rows.append(
                {
                    "project": project.name,
                    "author": comment.author.get_full_name() or comment.author.get_username(),
                    "content": comment.content[:MAX_COMMENT_CHARS],
                    "created_at": _text(comment.created_at),
                }
            )
            if len(rows) >= MAX_ITEMS_PER_TOOL:
                break
        if len(rows) >= MAX_ITEMS_PER_TOOL:
            break
    return ToolResult("comments.read", {"count": len(rows), "comments": rows})


def finance_tool(user, projects):
    project_roles = {
        project.pk: project_role_for(user=user, project=project) for project in projects
    }
    full_finance_projects = [
        project for project in projects
        if user.is_superuser or project_roles[project.pk] in {
            ProjectMembership.Role.ENGINEER,
            ProjectMembership.Role.PIVOT_REVIEWER,
        }
    ]
    own_payment_projects = [
        project for project in projects
        if project_roles[project.pk] == ProjectMembership.Role.OWNER
    ]
    if own_payment_projects and not full_finance_projects:
        rows = []
        total = Decimal("0")
        successful_count = 0
        for project in own_payment_projects:
            payments = project.payment_transactions.filter(user=user).order_by("-requested_at")
            for payment in payments[:MAX_ITEMS_PER_TOOL]:
                rows.append(
                    {
                        "project": project.name,
                        "amount_xaf": _text(payment.amount),
                        "currency": payment.currency,
                        "operator": payment.operator,
                        "status": payment.status,
                        "status_label": payment.get_status_display(),
                        "requested_at": _text(payment.requested_at),
                    }
                )
                if payment.status == PaymentTransaction.Status.SUCCESS:
                    total += payment.amount
                    successful_count += 1
                if len(rows) >= MAX_ITEMS_PER_TOOL:
                    break
        return ToolResult(
            "payments.read_own",
            {
                "scope": "own_payments_only",
                "successful_total_xaf": _text(total),
                "successful_payment_count": successful_count,
                "payments": rows,
            },
        )
    if not full_finance_projects:
        raise ToolPermissionDenied(SAFE_DENIAL)
    rows = []
    for project in full_finance_projects:
        totals = financial_totals(project)
        rows.append(
            {
                "project": project.name,
                "budget_xaf": _text(totals["budget"]),
                "paid_xaf": _text(totals["paid"]),
                "withdrawn_xaf": _text(totals["withdrawn"]),
                "available_xaf": _text(totals["available"]),
                "remaining_xaf": _text(totals["remaining"]),
                "payment_count": project.payment_transactions.count(),
                "withdrawal_count": project.withdrawals.count(),
            }
        )
    data = {"projects": rows}
    if own_payment_projects:
        own_successful = PaymentTransaction.objects.filter(
            project__in=own_payment_projects,
            user=user,
            status=PaymentTransaction.Status.SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        data["owner_scope"] = {
            "projects": [project.name for project in own_payment_projects],
            "own_successful_payments_xaf": _text(own_successful),
        }
    return ToolResult("finance.read_project", data)


def report_tool(user, projects):
    rows = []
    for project in projects:
        project_role = project_role_for(user=user, project=project)
        stock_value = sum((item.total_price for item in project.stock_items.all()), Decimal("0"))
        row = {
            "project": project.name,
            "status": project.status,
            "progress_percent": _progress(project),
            "stage_count": project.stages.count(),
            "completed_stage_count": project.stages.filter(status="complete").count(),
            "stock_item_count": project.stock_items.count(),
            "stock_value_xaf": _text(stock_value),
            "approved_document_count": project.documents.filter(status="approved").count(),
            "photo_count": project.gallery_images.count(),
            "comment_count": project.comments.filter(is_deleted=False).count(),
        }
        if project_role == ProjectMembership.Role.OWNER and not user.is_superuser:
            row["own_successful_payments_xaf"] = _text(
                project.payment_transactions.filter(user=user, status="success").aggregate(
                    value=Sum("amount")
                )["value"]
                or Decimal("0")
            )
        elif user.is_superuser or project_role in {
            ProjectMembership.Role.ENGINEER,
            ProjectMembership.Role.PIVOT_REVIEWER,
        }:
            totals = financial_totals(project)
            row["paid_xaf"] = _text(totals["paid"])
            row["withdrawn_xaf"] = _text(totals["withdrawn"])
        rows.append(row)
    return ToolResult("reports.read", {"projects": rows})


def subscription_tool(user, question=""):
    if not (user.is_superuser or user.organization_id):
        raise ToolPermissionDenied(SAFE_DENIAL)
    normalized = str(question or "").casefold()
    subscriptions = OrganizationSubscription.objects.select_related(
        "organization", "plan", "pending_plan"
    )
    if user.is_superuser:
        mentioned = [
            organization for organization in Organization.objects.all()
            if organization.name.casefold() in normalized
        ]
        if mentioned:
            subscriptions = subscriptions.filter(
                organization_id__in=[organization.pk for organization in mentioned]
            )
    else:
        subscriptions = subscriptions.filter(organization_id=user.organization_id)
    rows = []
    for subscription in subscriptions.order_by("organization__name")[:MAX_ITEMS_PER_TOOL]:
        usage = quota_usage(subscription.organization)
        rows.append({
            "organization": subscription.organization.name,
            "plan": subscription.plan.name,
            "plan_code": subscription.plan.code,
            "status": subscription.status,
            "status_label": subscription.get_status_display(),
            "billing_cycle": subscription.billing_cycle,
            "billing_cycle_label": subscription.get_billing_cycle_display(),
            "trial_ends_at": _text(subscription.trial_ends_at),
            "current_period_ends_at": _text(subscription.current_period_ends_at),
            "grace_ends_at": _text(subscription.grace_ends_at),
            "pending_plan": subscription.pending_plan.name if subscription.pending_plan else None,
            "pending_effective_at": _text(subscription.pending_effective_at),
            "active_projects": usage["projects"].used,
            "project_limit": usage["projects"].limit,
            "internal_members": usage["members"].used,
            "member_limit": usage["members"].limit,
            "ai_assistant_enabled": bool(subscription.plan_snapshot.get("ai_assistant_enabled", subscription.plan.ai_assistant_enabled)),
            "advanced_reports_enabled": bool(subscription.plan_snapshot.get("advanced_reports_enabled", subscription.plan.advanced_reports_enabled)),
        })
    return ToolResult(
        "subscriptions.read",
        {"scope": "platform" if user.is_superuser else "current_organization", "count": len(rows), "subscriptions": rows},
    )


TOOL_HANDLERS = {
    "subscription": subscription_tool,
    "platform": platform_tool,
    "projects": project_tool,
    "stages": stage_tool,
    "stock": stock_tool,
    "documents": document_tool,
    "photos": photo_tool,
    "comments": comment_tool,
    "finance": finance_tool,
    "report": report_tool,
}


def run_read_tools(user, question):
    intents = detect_intents(question)
    if not intents:
        return []
    projects = _selected_projects(user, question)
    results = []
    for intent in intents:
        if intent == "subscription":
            results.append(subscription_tool(user, question))
        elif intent == "users":
            results.append(user_directory_tool(user, question))
        elif intent == "platform":
            results.append(platform_tool(user, projects, question))
        else:
            results.append(TOOL_HANDLERS[intent](user, projects))
    return results


def tool_context_json(results):
    return json.dumps(
        [{"tool": result.name, "data": result.data} for result in results],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deterministic_tool_answer(results, language="fr"):
    if not results:
        return None
    english = str(language).lower().startswith("en")
    sections = []
    for result in results:
        data = result.data
        if result.name == "payments.read_own":
            total = data["successful_total_xaf"]
            count = data["successful_payment_count"]
            sections.append(
                f"You have successfully paid {total} XAF across {count} payment(s)."
                if english
                else (
                    f"Vous avez déjà payé un total de {total} XAF sur {count} "
                    "paiement(s) réussi(s)."
                )
            )
        elif result.name == "subscriptions.read":
            rows = data["subscriptions"]
            if not rows:
                sections.append("No authorized subscription was found." if english else "Aucun abonnement autorisé n’a été trouvé.")
            else:
                details = []
                for row in rows:
                    end = row["current_period_ends_at"] or row["trial_ends_at"] or "—"
                    project_limit = row["project_limit"] if row["project_limit"] is not None else "∞"
                    member_limit = row["member_limit"] if row["member_limit"] is not None else "∞"
                    if english:
                        details.append(f"{row['organization']}: {row['plan']} ({row['status_label']}), {row['billing_cycle_label']}, next deadline {end}, projects {row['active_projects']}/{project_limit}, internal members {row['internal_members']}/{member_limit}")
                    else:
                        details.append(f"{row['organization']} : forfait {row['plan']} ({row['status_label']}), {row['billing_cycle_label']}, prochaine échéance {end}, projets actifs {row['active_projects']}/{project_limit}, membres internes {row['internal_members']}/{member_limit}")
                sections.append(("Subscriptions: " if english else "Abonnements : ") + "; ".join(details) + ".")
        elif result.name == "platform.statistics":
            rows = data["organizations"]
            if rows:
                details = "; ".join(f"{row['name']} — {row['status_label']}" for row in rows)
                sections.append(
                    f"Organizations ({data['organization_count']}): {details}."
                    if english
                    else f"Organisations ({data['organization_count']}) : {details}."
                )
            else:
                sections.append(
                    "No authorized organization was found."
                    if english
                    else "Aucune organisation autorisée n’a été trouvée."
                )
        elif result.name == "users.directory":
            rows = data["users"]
            if rows:
                details = "; ".join(
                    f"{row['name']} ({row['username']}) — {row['role_label']}" for row in rows
                )
                sections.append(
                    f"Users ({data['user_count']}): {details}."
                    if english
                    else f"Utilisateurs ({data['user_count']}) : {details}."
                )
            else:
                sections.append(
                    "No authorized user was found."
                    if english
                    else "Aucun utilisateur autorisé n’a été trouvé."
                )
        elif result.name == "projects.read":
            rows = data["projects"]
            details = "; ".join(
                f"{row['name']} — {row['status_label']}, {row['progress_percent']}%" for row in rows
            )
            sections.append(
                (f"Projects ({data['count']}): {details}." if details else "No accessible project.")
                if english
                else (
                    f"Projets accessibles ({data['count']}) : {details}."
                    if details
                    else "Aucun projet accessible n’a été trouvé."
                )
            )
        elif result.name == "stages.read":
            rows = data["stages"]
            details = "; ".join(
                f"{row['project']} / {row['title']} — {row['status_label']}, "
                f"{row['progress_percent']}%"
                for row in rows
            )
            sections.append(
                f"Étapes ({data['count']}) : {details}."
                if details
                else "Aucune étape accessible n’a été trouvée."
            )
        elif result.name == "stock.read":
            rows = data["items"]
            details = "; ".join(
                f"{row['project']} / {row['name']} : {row['quantity']} {row['unit']}"
                f"{' — stock faible' if row['is_low_stock'] else ''}"
                for row in rows
            )
            sections.append(
                f"Articles en stock ({data['count']}) : {details}."
                if details
                else "Aucun article en stock accessible n’a été trouvé."
            )
        elif result.name == "documents.read":
            rows = data["documents"]
            details = "; ".join(
                f"{row['project']} / {row['title']} — {row['status_label']}" for row in rows
            )
            sections.append(
                f"Documents ({data['count']}) : {details}."
                if details
                else "Aucun document accessible n’a été trouvé."
            )
        elif result.name == "photos.read":
            rows = data["photos"]
            details = "; ".join(
                f"{row['project']} / {row['caption'] or 'Photo sans légende'}" for row in rows
            )
            sections.append(
                f"Photos ({data['count']}) : {details}."
                if details
                else "Aucune photo accessible n’a été trouvée."
            )
        elif result.name == "comments.read":
            rows = data["comments"]
            details = "; ".join(
                f"{row['project']} / {row['author']} : {row['content']}" for row in rows
            )
            sections.append(
                f"Commentaires ({data['count']}) : {details}."
                if details
                else "Aucun commentaire accessible n’a été trouvé."
            )
        elif result.name == "finance.read_project":
            rows = data["projects"]
            details = "; ".join(
                f"{row['project']} — payé : {row['paid_xaf']} XAF, retiré : "
                f"{row['withdrawn_xaf']} XAF, disponible : {row['available_xaf']} XAF"
                for row in rows
            )
            sections.append(
                f"Finances : {details}."
                if details
                else "Aucune donnée financière accessible n’a été trouvée."
            )
        elif result.name == "reports.read":
            rows = data["projects"]
            details = "; ".join(
                f"{row['project']} — {row['status']}, progression {row['progress_percent']}%, "
                f"{row['completed_stage_count']}/{row['stage_count']} étape(s) terminée(s)"
                for row in rows
            )
            sections.append(
                f"Rapport : {details}."
                if details
                else "Aucune donnée de rapport accessible n’a été trouvée."
            )
    return "\n\n".join(sections) or None
