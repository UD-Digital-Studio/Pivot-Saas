from django.urls import Resolver404, resolve

from apps.projects.models import Project


PROJECT_PK_NAMESPACES = {"projects", "reporting"}


def request_project_id(request):
    """Return the project targeted by the current route, when applicable."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        try:
            match = resolve(request.path_info)
        except Resolver404:
            return None
    if "project_pk" in match.kwargs:
        return match.kwargs["project_pk"]
    if match.namespace in PROJECT_PK_NAMESPACES and "pk" in match.kwargs:
        return match.kwargs["pk"]
    return None


def effective_subscription_organization_id(request):
    """Use the project's tenant for project work, otherwise the account tenant."""
    user = request.user
    if not user.is_authenticated:
        return None
    project_id = request_project_id(request)
    if project_id is not None:
        organization_id = Project.objects.filter(pk=project_id).values_list(
            "organization_id", flat=True
        ).first()
        if organization_id is not None:
            return organization_id
    return user.organization_id
