from django.contrib import admin

from .models import OrganizationSubscription, SubscriptionEvent, SubscriptionNoticeDelivery, SubscriptionPayment, SubscriptionPlan


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "monthly_price",
        "yearly_price",
        "currency",
        "is_active",
        "is_public",
    )
    list_filter = ("is_active", "is_public", "currency")
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OrganizationSubscription)
class OrganizationSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "billing_cycle", "updated_at")
    list_filter = ("status", "billing_cycle", "plan")
    search_fields = ("organization__name", "organization__slug", "plan__name")
    readonly_fields = ("plan_snapshot", "created_at", "updated_at")


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "subscription", "previous_status", "new_status", "occurred_at")
    list_filter = ("event_type", "new_status")
    search_fields = ("subscription__organization__name", "event_type")
    readonly_fields = (
        "subscription",
        "actor",
        "event_type",
        "previous_status",
        "new_status",
        "plan_snapshot",
        "metadata",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "billing_cycle", "amount", "status", "requested_at")
    list_filter = ("status", "billing_cycle", "plan", "operator")
    search_fields = ("organization__name", "provider_reference", "payer_phone")
    readonly_fields = tuple(field.name for field in SubscriptionPayment._meta.fields)

    def has_add_permission(self, request):
        return False


@admin.register(SubscriptionNoticeDelivery)
class SubscriptionNoticeDeliveryAdmin(admin.ModelAdmin):
    list_display = ("subscription", "recipient", "milestone", "channel", "delivered_at")
    list_filter = ("milestone", "channel")
    readonly_fields = tuple(field.name for field in SubscriptionNoticeDelivery._meta.fields)

    def has_add_permission(self, request):
        return False
