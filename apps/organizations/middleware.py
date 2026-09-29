from django.core.exceptions import PermissionDenied

from .models import Organization


class ActiveOrganizationMiddleware:
    """Stop a business user whenever its tenant is not active."""

    allowed_prefixes = ("/comptes/deconnexion/", "/static/", "/media/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not user.is_superuser
            and user.organization_id
            and not request.path.startswith(self.allowed_prefixes)
            and user.organization.status != Organization.Status.ACTIVE
        ):
            raise PermissionDenied
        return self.get_response(request)
