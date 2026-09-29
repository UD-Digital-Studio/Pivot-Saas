from django.contrib import admin

from .models import StockItem, StockMovement


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "quantity", "unit", "status", "updated_at")
    list_filter = ("status", "organization")
    search_fields = ("name", "project__name")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("item", "movement_type", "source_quantity", "source_unit", "variation", "resulting_quantity", "actor", "created_at")
    readonly_fields = (
        "organization",
        "project",
        "item",
        "movement_type",
        "source_reference",
        "source_quantity",
        "source_unit",
        "conversion_factor",
        "normalized_quantity",
        "variation",
        "resulting_quantity",
        "reason",
        "actor",
        "idempotency_key",
        "created_at",
    )
