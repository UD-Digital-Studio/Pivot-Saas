from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin

from .models import Invitation, Notification, User, UserProfile
from .services import activate_engineer


@admin.register(User)
class PivotUserAdmin(UserAdmin):
    list_display = ("username", "email", "organization", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "organization")
    search_fields = ("username", "email", "organization__name")
    actions = ("activate_selected_engineers",)

    fieldsets = UserAdmin.fieldsets + (("PIVOT-SASS", {"fields": ("organization", "role")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("PIVOT-SASS", {"fields": ("organization", "role")}),
    )

    @admin.action(description="Activer les comptes ingénieur sélectionnés")
    def activate_selected_engineers(self, request, queryset):
        activated = 0
        for engineer in queryset.filter(role=User.Role.ENGINEER, is_active=False):
            activate_engineer(actor=request.user, engineer=engineer)
            activated += 1
        self.message_user(
            request,
            f"{activated} compte(s) ingénieur activé(s).",
            level=messages.SUCCESS,
        )


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "role", "invited_by", "expires_at", "accepted_at")
    list_filter = ("role", "organization", "accepted_at")
    search_fields = ("email", "organization__name", "invited_by__username")
    readonly_fields = (
        "organization",
        "invited_by",
        "email",
        "role",
        "token_hash",
        "expires_at",
        "accepted_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "location", "updated_at")
    search_fields = ("user__username", "user__email", "phone", "location")
    readonly_fields = ("updated_at",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "kind", "is_read", "created_at")
    list_filter = ("kind", "is_read", "organization")
    search_fields = ("title", "recipient__username", "recipient__email")
    readonly_fields = (
        "organization",
        "recipient",
        "actor",
        "kind",
        "title",
        "message",
        "target_url",
        "is_read",
        "created_at",
        "read_at",
    )

    def has_add_permission(self, request):
        return False
