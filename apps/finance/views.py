import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect

from apps.projects.selectors import projects_for_user

from .forms import ExpenseAttachmentDecisionForm, ExpenseAttachmentForm, ExpenseOwnerDecisionForm, ExpensePaymentForm, ExpensePivotVerificationForm, ExpenseRequestForm, ExpenseTechnicalOpinionForm, ExpenseTransitionForm, PaymentForm, WithdrawalForm
from .models import ExpenseRequest, ExpenseRequestAttachment, PaymentTransaction, Withdrawal
from .services import attach_expense_evidence, create_expense_request, decide_expense_by_owner, decide_withdrawal, initiate_expense_payment, initiate_payment, reconcile_payment, reject_expense_attachment, replace_expense_attachment, request_withdrawal, submit_expense_pivot_verification, submit_expense_technical_opinion, transition_expense_request


def finance_back(project):
    return redirect(f"{project.get_absolute_url()}?tab=finance")


def expense_back(project):
    return redirect(f"{project.get_absolute_url()}?tab=expenses")


@login_required
def expense_create(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseRequestForm(request.POST, project=project)
    if form.is_valid():
        try:
            expense_request = create_expense_request(actor=request.user, project=project, data=form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f"Demande de dépense créée : {expense_request.get_status_display()}.")
    else:
        messages.error(request, "La demande de dépense est incomplète ou invalide.")
    return expense_back(project)


@login_required
def expense_transition(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project, organization=project.organization)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseTransitionForm(request.POST)
    if form.is_valid():
        try:
            updated = transition_expense_request(actor=request.user, expense_request=expense_request, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, f"Demande passée au statut {updated.get_status_display()}.")
    else:
        messages.error(request, "Transition invalide.")
    return expense_back(project)


@login_required
def expense_attachment_add(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseAttachmentForm(request.POST, project=project)
    if form.is_valid():
        try:
            attach_expense_evidence(actor=request.user, expense_request=expense_request, **form.cleaned_data)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "La pièce a été ajoutée au dossier.")
    else:
        messages.error(request, "La pièce sélectionnée est invalide.")
    return expense_back(project)


@login_required
def expense_attachment_reject(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    attachment = get_object_or_404(ExpenseRequestAttachment, pk=pk, request__project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseAttachmentDecisionForm(request.POST, project=project)
    if form.is_valid():
        reject_expense_attachment(actor=request.user, attachment=attachment, reason=form.cleaned_data["reason"])
        messages.success(request, "La pièce a été rejetée sans supprimer son historique.")
    else:
        messages.error(request, "Le motif de rejet est obligatoire.")
    return expense_back(project)


@login_required
def expense_attachment_replace(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    attachment = get_object_or_404(ExpenseRequestAttachment, pk=pk, request__project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseAttachmentDecisionForm(request.POST, project=project, replacement_required=True)
    if form.is_valid():
        try:
            replace_expense_attachment(actor=request.user, attachment=attachment, replacement_evidence=form.cleaned_data["replacement_evidence"], reason=form.cleaned_data["reason"])
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "La nouvelle pièce remplace l’ancienne, conservée dans l’historique.")
    else:
        messages.error(request, "La preuve de remplacement et le motif sont obligatoires.")
    return expense_back(project)


@login_required
def expense_technical_opinion(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseTechnicalOpinionForm(request.POST)
    if form.is_valid():
        try:
            opinion, updated = submit_expense_technical_opinion(
                actor=request.user, expense_request=expense_request, **form.cleaned_data
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                f"Avis technique {opinion.get_decision_display().lower()} enregistré. "
                f"La demande est maintenant {updated.get_status_display().lower()}.",
            )
    else:
        messages.error(request, "La décision technique et son motif sont obligatoires.")
    return expense_back(project)


@login_required
def expense_pivot_verification(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpensePivotVerificationForm(request.POST, allow_exceptional=request.user.is_superuser)
    if form.is_valid():
        payload = form.cleaned_data
        payload.setdefault("is_exceptional", False)
        payload.setdefault("confirmation", "")
        try:
            verification, updated = submit_expense_pivot_verification(
                actor=request.user, expense_request=expense_request, **payload
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                f"Vérification PIVOT {verification.get_decision_display().lower()} enregistrée. "
                f"La demande reste {updated.get_status_display().lower()}.",
            )
    else:
        messages.error(request, "La décision PIVOT et sa motivation sont obligatoires.")
    return expense_back(project)


@login_required
def expense_owner_decision(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpenseOwnerDecisionForm(request.POST)
    if form.is_valid():
        try:
            owner_decision, updated = decide_expense_by_owner(
                actor=request.user, expense_request=expense_request, **form.cleaned_data
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(
                request,
                f"Décision enregistrée : {owner_decision.get_decision_display()}. "
                f"La demande est maintenant {updated.get_status_display().lower()}.",
            )
    else:
        messages.error(request, "Le refus exige un motif et une version valide du dossier.")
    return expense_back(project)


@login_required
def expense_pay(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    expense_request = get_object_or_404(ExpenseRequest, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    form = ExpensePaymentForm(request.POST)
    if form.is_valid():
        try:
            tx, created = initiate_expense_payment(
                actor=request.user, expense_request=expense_request, **form.cleaned_data
            )
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            if not created:
                messages.info(request, "Une tentative existe déjà pour cette demande.")
            elif tx.status == PaymentTransaction.Status.SUCCESS:
                messages.success(request, "Paiement MeSomb confirmé et dépense comptabilisée.")
            elif tx.status == PaymentTransaction.Status.PENDING:
                messages.info(request, "Paiement transmis à MeSomb. La dépense ne sera comptabilisée qu’après confirmation.")
            else:
                messages.error(request, "Le paiement a été refusé ou n’a pas abouti.")
    else:
        messages.error(request, "Opérateur ou téléphone invalide.")
    return finance_back(project)


@login_required
def pay(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = PaymentForm(request.POST)
    if form.is_valid():
        tx, created = initiate_payment(actor=request.user, project=project, **form.cleaned_data)
        if not created:
            messages.info(request, "Cette demande de paiement a déjà été enregistrée.")
        elif tx.status == "success":
            messages.success(request, "Paiement MeSomb confirmé.")
        elif tx.status == "pending":
            messages.info(request, "Paiement transmis à MeSomb et en attente de confirmation.")
        else:
            messages.error(request, "Le paiement n’a pas abouti. Vérifiez le numéro et réessayez.")
    else:
        messages.error(request, "Informations de paiement invalides.")
    return finance_back(project)


@login_required
def withdraw(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if request.method != "POST":
        raise PermissionDenied
    form = WithdrawalForm(request.POST)
    if form.is_valid():
        try:
            request_withdrawal(actor=request.user, project=project, **form.cleaned_data)
            messages.success(request, "Demande de retrait créée.")
        except ValidationError as e:
            messages.error(request, e.messages[0])
    return finance_back(project)


@login_required
def payment_refresh(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    if request.method != "POST":
        raise PermissionDenied
    tx = get_object_or_404(PaymentTransaction, pk=pk, project=project)
    tx, changed = reconcile_payment(actor=request.user, transaction_id=tx.pk)
    if changed:
        messages.success(request, f"Statut MeSomb actualisé : {tx.get_status_display()}.")
    else:
        messages.info(request, "Aucun nouveau statut MeSomb n’est disponible.")
    return finance_back(project)


@login_required
def withdrawal_decide(request, project_pk, pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    withdrawal = get_object_or_404(Withdrawal, pk=pk, project=project)
    if request.method != "POST":
        raise PermissionDenied
    decide_withdrawal(actor=request.user, withdrawal=withdrawal, status=request.POST.get("status"))
    return finance_back(project)


@login_required
def export(request, project_pk):
    project = get_object_or_404(projects_for_user(request.user), pk=project_pk)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="finances.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["Type", "Date", "Montant", "Statut", "Référence"])
    for tx in project.payment_transactions.all():
        writer.writerow(
            [
                "Paiement",
                tx.requested_at.isoformat(),
                tx.amount,
                tx.get_status_display(),
                tx.provider_reference,
            ]
        )
    for wd in project.withdrawals.all():
        writer.writerow(
            ["Retrait", wd.requested_at.isoformat(), wd.amount, wd.get_status_display(), str(wd.pk)]
        )
    return response
