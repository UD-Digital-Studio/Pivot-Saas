from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import OrganizationSubscription
from .access import effective_subscription_organization_id


class SubscriptionAccessMiddleware:
    """Enforce tenant write restrictions consistently for HTML, API and AJAX."""

    safe_methods = {"GET", "HEAD", "OPTIONS"}
    allowed_prefixes = ("/tarifs/", "/comptes/deconnexion/", "/i18n/", "/static/", "/media/")
    restricted_statuses = {
        OrganizationSubscription.Status.READ_ONLY,
        OrganizationSubscription.Status.SUSPENDED,
        OrganizationSubscription.Status.EXPIRED,
        OrganizationSubscription.Status.CANCELLED,
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.SUBSCRIPTIONS_ENABLED:
            return self.get_response(request)
        user = request.user
        organization_id = effective_subscription_organization_id(request)
        report_generation = request.path.startswith("/rapports/projets/") and request.path.endswith(("/pdf/", "/csv/"))
        if (
            (request.method not in self.safe_methods or report_generation)
            and user.is_authenticated
            and not user.is_superuser
            and organization_id
            and not request.path.startswith(self.allowed_prefixes)
        ):
            subscription = OrganizationSubscription.objects.filter(
                organization_id=organization_id
            ).only("status").first()
            if subscription and subscription.status in self.restricted_statuses:
                message = "Votre organisation est en lecture seule. Renouvelez l’abonnement pour effectuer cette action."
                accepts_json = request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", "")
                if accepts_json:
                    return JsonResponse({"error": "subscription_read_only", "message": message, "billing_url": "/tarifs/"}, status=403)
                messages.error(request, message)
                return redirect("subscriptions:pricing")
        return self.get_response(request)
