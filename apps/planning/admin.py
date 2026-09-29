from django.contrib import admin

from .models import ProjectStage


@admin.register(ProjectStage)
class ProjectStageAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "status", "start_date", "end_date", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("title", "project__name")
