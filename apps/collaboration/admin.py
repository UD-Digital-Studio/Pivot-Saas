from django.contrib import admin

from .models import EvidenceRecord, ProjectComment, ProjectDocument, ProjectImage

admin.site.register(ProjectDocument)
admin.site.register(ProjectImage)
admin.site.register(ProjectComment)

@admin.register(EvidenceRecord)
class EvidenceRecordAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "evidence_type", "version", "status", "captured_at")
    list_filter = ("status", "evidence_type", "is_administrative_correction")
    readonly_fields = tuple(field.name for field in EvidenceRecord._meta.fields)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        if obj and obj.status in {EvidenceRecord.Status.VERIFIED, EvidenceRecord.Status.APPROVED}:
            return False
        return request.user.is_superuser

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
