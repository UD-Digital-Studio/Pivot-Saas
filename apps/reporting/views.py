from django.utils.translation import gettext_lazy as _
import csv
import base64
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from apps.projects.selectors import projects_for_user
from apps.subscriptions.quotas import subscription_feature_enabled
from apps.collaboration.services import can_access_evidence
from apps.audit.models import AuditEvent

from .services import parse_period, project_report_projection, stage_verification_report_projection


@login_required
def center(request):
    projects = projects_for_user(request.user)
    return render(request, "reporting/center.html", {"projects": projects})


def selected(request, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=pk)
    start, end = parse_period(request.GET.get("date_from", ""), request.GET.get("date_to", ""))
    data = project_report_projection(project=project, date_from=start, date_to=end)
    data["evidence_records"] = [
        evidence for evidence in data["evidence_records"]
        if can_access_evidence(actor=request.user, evidence=evidence, action="export")
    ]
    return data


def audit_report_evidence_export(request, data, export_format):
    if not data["evidence_records"]:
        return
    AuditEvent.objects.create(
        organization=data["project"].organization, actor=request.user,
        action="evidence.exported", target_type="project", target_id=str(data["project"].pk),
        metadata={"format": export_format, "versions": [{"id": str(item.pk), "version": item.version} for item in data["evidence_records"]]},
    )


@login_required
def project_pdf(request, pk):
    if not subscription_feature_enabled(request.user.organization, "advanced_reports_enabled"):
        messages.error(request, _("Votre forfait n’inclut pas les rapports avancés."))
        return center(request)
    try:
        data = selected(request, pk)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return center(request)
    logo_bytes = (settings.BASE_DIR / "static" / "images" / "Logo.png").read_bytes()
    audit_report_evidence_export(request, data, "pdf")
    data["logo_data_uri"] = "data:image/png;base64," + base64.b64encode(logo_bytes).decode("ascii")
    html = render_to_string("reporting/project_pdf.html", data)
    output = BytesIO()
    result = pisa.CreatePDF(html, dest=output, encoding="utf-8")
    if result.err:
        return HttpResponse("Le rapport PDF n'a pas pu être généré.", status=500)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="rapport-{data["project"].pk}.pdf"'
    return response


@login_required
def project_csv(request, pk):
    if not subscription_feature_enabled(request.user.organization, "advanced_reports_enabled"):
        messages.error(request, _("Votre forfait n’inclut pas les rapports avancés."))
        return center(request)
    data = selected(request, pk)
    audit_report_evidence_export(request, data, "csv")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="rapport-projet.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Section", "Date", "Libellé", "Montant/Quantité", "Statut"])
    for stage in data["stages"]:
        writer.writerow(
            ["Étape", stage.start_date, stage.title, stage.actual_cost, stage.get_status_display()]
        )
        declared = stage.latest_declared_progress
        if declared:
            writer.writerow([
                "Progression déclarée", declared.created_at.isoformat(), stage.title,
                declared.percent, f"Source : {declared.author.get_username()}",
            ])
        verified = stage.latest_verified_progress
        if verified:
            writer.writerow([
                "Progression vérifiée", verified.created_at.isoformat(), stage.title,
                verified.percent, f"Source : {verified.author.get_username()}",
            ])
    for item in data["stock"]:
        writer.writerow(["Stock", "", item.name, item.quantity, item.get_status_display()])
    for tx in data["payments"]:
        if tx.expense_request_id:
            continue
        writer.writerow(
            [
                "Paiement",
                tx.requested_at.isoformat(),
                tx.provider_reference,
                tx.amount,
                tx.get_status_display(),
            ]
        )
    for expense in data["expense_requests"]:
        writer.writerow(["Demande de dépense", expense.created_at.isoformat(), expense.purpose, expense.amount, expense.get_status_display()])
    for decision in data["expense_authorizations"]:
        writer.writerow(["Autorisation propriétaire", decision.created_at.isoformat(), f"{decision.request.purpose} · version {decision.decided_status_version}", decision.request.amount, decision.get_decision_display()])
    for tx in data["payment_attempts"]:
        writer.writerow(["Tentative de paiement", tx.requested_at.isoformat(), tx.pivot_reference, tx.amount, tx.get_status_display()])
    for tx in data["accounted_payments"]:
        writer.writerow(["Succès comptabilisé", tx.completed_at.isoformat() if tx.completed_at else "", tx.provider_reference or tx.pivot_reference, tx.amount, tx.get_status_display()])
    for wd in data["withdrawals"]:
        writer.writerow(
            ["Retrait", wd.requested_at.isoformat(), wd.reason, wd.amount, wd.get_status_display()]
        )
    for evidence in data["evidence_records"]:
        writer.writerow([
            "Preuve", evidence.captured_at.isoformat(),
            f"{evidence.title} · version {evidence.version}",
            evidence.get_evidence_type_display(), evidence.get_status_display(),
        ])
    return response


@login_required
def stage_verification_pdf(request, project_pk, stage_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    stage = get_object_or_404(project.stages.all(), pk=stage_pk)
    try:
        data = stage_verification_report_projection(actor=request.user, stage=stage)
    except ValidationError as error:
        return HttpResponse(error.messages[0], status=409)
    logo_bytes = (settings.BASE_DIR / "static" / "images" / "Logo.png").read_bytes()
    data["logo_data_uri"] = "data:image/png;base64," + base64.b64encode(logo_bytes).decode("ascii")
    AuditEvent.objects.create(
        organization=project.organization, actor=request.user,
        action="stage_verification_report.exported",
        target_type="stage_verification_report", target_id=str(data["report"].pk),
        metadata={"reference": data["report"].reference, "stage_id": str(stage.pk),
                  "evidence_ids": [str(item.pk) for item in data["proofs"]]},
    )
    html = render_to_string("reporting/stage_verification_pdf.html", data)
    output = BytesIO()
    result = pisa.CreatePDF(html, dest=output, encoding="utf-8")
    if result.err:
        return HttpResponse("Le rapport de vérification n'a pas pu être généré.", status=500)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="verification-{data["report"].reference}.pdf"'
    return response
