from django.conf import settings

from .models import OrganizationSubscription
from .access import effective_subscription_organization_id


def subscription_access(request):
    if not settings.SUBSCRIPTIONS_ENABLED:
        return {}
    if not request.user.is_authenticated:
        return {}
    organization_id = effective_subscription_organization_id(request)
    if not organization_id:
        return {}
    subscription = OrganizationSubscription.objects.filter(
        organization_id=organization_id
    ).select_related("plan").first()
    if not subscription:
        return {}
    return {
        "access_subscription": subscription,
        "subscription_is_read_only": subscription.status in {
            OrganizationSubscription.Status.READ_ONLY,
            OrganizationSubscription.Status.SUSPENDED,
            OrganizationSubscription.Status.EXPIRED,
            OrganizationSubscription.Status.CANCELLED,
        },
        "subscription_is_grace": subscription.status == OrganizationSubscription.Status.GRACE,
    }
