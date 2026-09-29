from django.db.models import QuerySet
from apps.accounts.models import User

from .models import Project
from .access import projects_visible_to


def projects_for_user(user: User) -> QuerySet[Project]:
    queryset = Project.objects.select_related("organization", "engineer")
    return projects_visible_to(user, queryset)
