from django.contrib import admin

from .models import Project, ProjectMembership, ProjectStatusHistory


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "engineer", "status", "budget_amount", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("name", "location", "engineer__username", "organization__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ("project", "user", "project_role", "organization", "created_at")
    list_filter = ("project_role", "organization")
    search_fields = ("project__name", "user__username", "user__email")


@admin.register(ProjectStatusHistory)
class ProjectStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("project", "previous_status", "new_status", "actor", "created_at")
    list_filter = ("previous_status", "new_status")
    readonly_fields = ("project", "previous_status", "new_status", "actor", "created_at")
