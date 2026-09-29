import base64
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST
from xhtml2pdf import pisa

from .forms import SubscriptionPaymentForm
from .models import SubscriptionEvent, SubscriptionPayment, SubscriptionPlan
from .quotas import quota_usage
from .services import initiate_subscription_payment, payment_action, reconcile_subscription_payment


def pricing(request):
    billing_cycle = request.GET.get("cycle", "monthly")
    if billing_cycle not in {"monthly", "yearly"}:
        billing_cycle = "monthly"
    plans = list(SubscriptionPlan.objects.filter(is_active=True, is_public=True).order_by(
        "display_order", "monthly_price"
    ))
    current_subscription = None
    pricing_in_app = bool(request.user.is_authenticated and request.user.organization_id)
    if request.user.is_authenticated and request.user.organization_id:
        current_subscription = getattr(request.user.organization, "subscription", None)
    if current_subscription:
        for plan in plans:
            plan.purchase_action = payment_action(current_subscription, plan)
            if plan.purchase_action == SubscriptionPayment.Action.UPGRADE:
                plan.purchase_note = "Montée de gamme immédiate ; vos jours déjà payés sont conservés."
            elif plan.purchase_action == SubscriptionPayment.Action.DOWNGRADE:
                plan.purchase_note = "Baisse appliquée à la prochaine échéance, sans suppression de données."
            else:
                plan.purchase_note = "Renouvellement ajouté après votre période déjà payée."
    payments = SubscriptionPayment.objects.none()
    if request.user.is_authenticated and request.user.organization_id:
        payments = SubscriptionPayment.objects.filter(organization=request.user.organization)[:10]
    return render(
        request,
        "subscriptions/pricing.html",
        {
            "plans": plans,
            "billing_cycle": billing_cycle,
            "current_subscription": current_subscription,
            "payment_form": SubscriptionPaymentForm(initial={"billing_cycle": billing_cycle}),
            "payments": payments,
            "pricing_in_app": pricing_in_app,
            "pricing_base_template": "base/app.html" if pricing_in_app else "base/auth.html",
        },
    )


@require_POST
@login_required
def pay(request):
    if not settings.SUBSCRIPTIONS_ENABLED:
        messages.error(request, "Le module commercial est temporairement désactivé.")
        return redirect("subscriptions:pricing")
    form = SubscriptionPaymentForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Vérifiez le forfait, l’opérateur et le numéro de téléphone.")
        return redirect("subscriptions:pricing")
    try:
        payment, created = initiate_subscription_payment(
            actor=request.user, plan=form.cleaned_data["plan"],
            billing_cycle=form.cleaned_data["billing_cycle"],
            operator=form.cleaned_data["operator"], phone=form.cleaned_data["phone"],
        )
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect("subscriptions:pricing")
    if not created:
        messages.warning(request, "Un paiement est déjà en cours. Sa vérification doit se terminer avant une nouvelle tentative.")
    elif payment.status == SubscriptionPayment.Status.SUCCESS:
        messages.success(request, "Paiement confirmé : votre abonnement est actif.")
    elif payment.response_summary.get("error") == "provider_configuration_invalid":
        messages.error(request, "MeSomb a refusé la configuration de l’application. Vérifiez la clé d’application et redémarrez Django avant de réessayer.")
    elif payment.status == SubscriptionPayment.Status.PENDING:
        if payment.response_summary.get("error") == "provider_unavailable":
            messages.error(request, "MeSomb est momentanément inaccessible. Aucun second paiement ne sera lancé avant la vérification de cette tentative.")
        else:
            messages.info(request, "Paiement en attente de confirmation par l’opérateur.")
    else:
        messages.error(request, f"Le paiement est {payment.get_status_display().lower()}.")
    return redirect("subscriptions:pricing")


@require_POST
@login_required
def reconcile(request, pk):
    payment = get_object_or_404(SubscriptionPayment, pk=pk, organization=request.user.organization)
    payment, _ = reconcile_subscription_payment(actor=request.user, payment=payment)
    messages.success(request, "Paiement confirmé : votre abonnement est actif.") if payment.status == SubscriptionPayment.Status.SUCCESS else messages.info(request, f"Statut actuel : {payment.get_status_display()}.")
    return redirect("subscriptions:pricing")


@require_GET
@login_required
def billing(request):
    if request.user.organization_id is None or request.user.role not in {request.user.Role.ENGINEER, request.user.Role.ADMIN}:
        raise PermissionDenied
    subscription = request.user.organization.subscription
    return render(request, "subscriptions/billing.html", {
        "subscription": subscription,
        "usage": quota_usage(request.user.organization),
        "payments": subscription.payments.select_related("plan", "requested_by").all(),
        "events": SubscriptionEvent.objects.filter(subscription=subscription).select_related("actor")[:50],
    })


@require_GET
@login_required
def receipt(request, pk):
    payment = get_object_or_404(
        SubscriptionPayment.objects.select_related("organization", "plan", "requested_by"), pk=pk
    )
    if payment.status != SubscriptionPayment.Status.SUCCESS or not payment.receipt_reference:
        raise PermissionDenied("Un justificatif est disponible uniquement après confirmation du paiement.")
    if not request.user.is_superuser and (
        request.user.organization_id != payment.organization_id
        or request.user.role not in {request.user.Role.ENGINEER, request.user.Role.ADMIN}
    ):
        raise PermissionDenied
    logo_bytes = (settings.BASE_DIR / "static" / "images" / "Logo.png").read_bytes()
    html = render_to_string("subscriptions/receipt_pdf.html", {
        "payment": payment,
        "logo_data_uri": "data:image/png;base64," + base64.b64encode(logo_bytes).decode("ascii"),
    })
    output = BytesIO()
    result = pisa.CreatePDF(html, dest=output, encoding="utf-8")
    if result.err:
        return HttpResponse("Le justificatif n’a pas pu être généré.", status=500)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="recu-{payment.receipt_reference}.pdf"'
    return response
