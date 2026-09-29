import csv
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.projects.selectors import projects_for_user

from .forms import (
    ExpectedRangeAssignmentForm, InventoryAnomalyDecisionForm,
    InventoryAnomalyResolutionForm, StockAdjustmentForm, StockImportForm, StockItemForm,
)
from .models import InventoryAnomaly, InventoryAnomalyResolution, StockItem
from .services import (
    adjust_stock, assign_expected_range, can_adjust_stock, can_configure_expected_ranges,
    decide_anomaly_resolution, propose_anomaly_resolution, record_stock_movement,
    verify_stock_item,
)


def stock_redirect(project):
    return redirect(f"{project.get_absolute_url()}?tab=stock")


@login_required
def item_create(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not can_adjust_stock(actor=request.user, project=project) or request.method != "POST":
        raise PermissionDenied
    form = StockItemForm(request.POST)
    if form.is_valid():
        opening_quantity = form.cleaned_data["quantity"]
        item = form.save(commit=False)
        item.organization = project.organization
        item.project = project
        item.created_by = request.user
        item.quantity = 0
        item.full_clean()
        item.save()
        if opening_quantity:
            record_stock_movement(
                actor=request.user, item=item, movement_type="delivered",
                source_quantity=opening_quantity, source_unit=item.unit, conversion_factor=1,
                source_reference="Stock initial", reason="Création de l'article",
                idempotency_key=uuid.uuid4(),
            )
        messages.success(request, "L'article a été ajouté au stock.")
    else:
        messages.error(request, "L'article est invalide. Vérifiez les valeurs saisies.")
    return stock_redirect(project)


@login_required
def item_adjust(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not can_adjust_stock(actor=request.user, project=project) or request.method != "POST":
        raise PermissionDenied
    item = get_object_or_404(StockItem, pk=pk, project=project, organization=project.organization)
    form = StockAdjustmentForm(request.POST, project=project)
    if form.is_valid():
        try:
            _, created = record_stock_movement(actor=request.user, item=item, **form.cleaned_data)
            messages.success(
                request,
                "Le mouvement de stock a été enregistré."
                if created
                else "Cette opération avait déjà été enregistrée.",
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
    else:
        messages.error(request, "Le mouvement demandé est invalide.")
    return stock_redirect(project)


@login_required
def item_verify(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    item = get_object_or_404(StockItem, pk=pk, project=project, organization=project.organization)
    if request.method != "POST":
        raise PermissionDenied
    verify_stock_item(actor=request.user, item=item)
    messages.success(request, "L'article a été vérifié.")
    return stock_redirect(project)


@login_required
def item_expected_range(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    item = get_object_or_404(StockItem, pk=pk, project=project, organization=project.organization)
    if request.method != "POST" or not can_configure_expected_ranges(actor=request.user, project=project):
        raise PermissionDenied
    form = ExpectedRangeAssignmentForm(request.POST, project=project, item=item)
    if form.is_valid():
        assign_expected_range(actor=request.user, item=item, **form.cleaned_data)
        messages.success(request, "La plage attendue versionnée a été associée à l'article.")
    else:
        messages.error(request, "La plage attendue est invalide. Vérifiez l'unité et les bornes.")
    return stock_redirect(project)


@login_required
def anomaly_resolution_propose(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    anomaly = get_object_or_404(InventoryAnomaly, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = InventoryAnomalyResolutionForm(request.POST, project=project)
    if form.is_valid():
        try:
            propose_anomaly_resolution(actor=request.user, anomaly=anomaly, **form.cleaned_data)
            messages.success(request, "La résolution a été soumise pour validation.")
        except (PermissionDenied, ValidationError) as error:
            if isinstance(error, PermissionDenied):
                raise
            messages.error(request, error.messages[0])
    else:
        messages.error(request, "Le responsable, le motif et au moins une preuve sont obligatoires.")
    return stock_redirect(project)


@login_required
def anomaly_resolution_decide(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    resolution = get_object_or_404(
        InventoryAnomalyResolution, pk=pk, anomaly__project=project
    )
    if request.method != "POST":
        raise PermissionDenied
    form = InventoryAnomalyDecisionForm(request.POST)
    if form.is_valid():
        decide_anomaly_resolution(actor=request.user, resolution=resolution, **form.cleaned_data)
        messages.success(request, "La décision sur la résolution a été enregistrée.")
    else:
        messages.error(request, "La décision et son motif sont obligatoires.")
    return stock_redirect(project)


@login_required
def import_template(request):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="modele-stock.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["nom", "unite", "prix_unitaire", "quantite", "seuil_alerte"])
    writer.writerow(["Ciment", "sac", "6500", "100", "20"])
    return response


@login_required
def stock_import(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if not can_adjust_stock(actor=request.user, project=project) or request.method != "POST":
        raise PermissionDenied
    form = StockImportForm(request.POST, request.FILES)
    rejected = []
    created = 0
    if form.is_valid():
        try:
            content = form.cleaned_data["file"].read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(content))
            required = {"nom", "unite", "prix_unitaire", "quantite", "seuil_alerte"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                rejected.append({"line": 1, "reason": "En-têtes CSV manquants ou invalides."})
            else:
                for line, row in enumerate(reader, start=2):
                    try:
                        opening_quantity = Decimal(row["quantite"])
                        if opening_quantity < 0:
                            raise ValidationError("La quantité initiale ne peut pas être négative.")
                        item = StockItem(
                            organization=project.organization,
                            project=project,
                            created_by=request.user,
                            name=row["nom"].strip(),
                            unit=row["unite"].strip(),
                            unit_price=Decimal(row["prix_unitaire"]),
                            quantity=Decimal("0"),
                            alert_threshold=Decimal(row["seuil_alerte"]),
                        )
                        item.full_clean()
                        item.save()
                        if opening_quantity:
                            record_stock_movement(
                                actor=request.user, item=item, movement_type="delivered",
                                source_quantity=opening_quantity, source_unit=item.unit,
                                conversion_factor=1, source_reference=f"Import CSV ligne {line}",
                                reason="Import du stock initial", idempotency_key=uuid.uuid4(),
                            )
                        created += 1
                    except (InvalidOperation, ValidationError, KeyError) as error:
                        rejected.append({"line": line, "reason": str(error)})
        except UnicodeDecodeError:
            rejected.append({"line": 1, "reason": "Le fichier doit être encodé en UTF-8."})
    else:
        rejected.append({"line": 1, "reason": "Fichier CSV invalide."})
    return render(
        request,
        "inventory/import_report.html",
        {"project": project, "created_count": created, "rejected": rejected},
    )


@login_required
def stock_export(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    movements = project.stock_movements.select_related("item", "actor")
    if date_from:
        movements = movements.filter(created_at__date__gte=date_from)
    if date_to:
        movements = movements.filter(created_at__date__lte=date_to)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="historique-stock-{project.pk}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Date", "Article", "Nature", "Source", "Quantité source", "Unité source", "Facteur", "Quantité convertie", "Variation", "Quantité résultante", "Motif", "Auteur"])
    for movement in movements:
        writer.writerow(
            [
                movement.created_at.isoformat(),
                movement.item.name,
                movement.get_movement_type_display(),
                movement.source_reference,
                movement.source_quantity,
                movement.source_unit,
                movement.conversion_factor,
                movement.normalized_quantity,
                movement.variation,
                movement.resulting_quantity,
                movement.reason,
                movement.actor.get_username(),
            ]
        )
    return response
