from datetime import timedelta

from django.conf import settings
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone

from .models import AssistantRequest


def assistant_health_snapshot(*, hours=24):
    """Return aggregate operational data without conversation or prompt content."""
    since = timezone.now() - timedelta(hours=hours)
    requests = AssistantRequest.objects.filter(created_at__gte=since)
    aggregates = requests.aggregate(
        volume=Count("id"),
        successful=Count("id", filter=Q(status=AssistantRequest.Status.SUCCESS)),
        errors=Count("id", filter=Q(status=AssistantRequest.Status.FAILED)),
        blocked=Count("id", filter=Q(status=AssistantRequest.Status.BLOCKED)),
        processing=Count("id", filter=Q(status=AssistantRequest.Status.PROCESSING)),
        average_latency_ms=Avg("latency_ms", filter=Q(status=AssistantRequest.Status.SUCCESS)),
        total_tokens=Sum("total_tokens"),
    )
    enabled = settings.OPENROUTER_ENABLED
    configured = bool(settings.OPENROUTER_API_KEY and settings.OPENROUTER_MODEL)
    if not enabled:
        availability = "disabled"
    elif not configured:
        availability = "misconfigured"
    elif aggregates["errors"] and not aggregates["successful"]:
        availability = "degraded"
    else:
        availability = "operational"
    volume = aggregates["volume"] or 0
    successful = aggregates["successful"] or 0
    return {
        "availability": availability,
        "enabled": enabled,
        "configured": configured,
        "window_hours": hours,
        "volume": volume,
        "successful": successful,
        "errors": aggregates["errors"] or 0,
        "blocked": aggregates["blocked"] or 0,
        "processing": aggregates["processing"] or 0,
        "average_latency_ms": round(aggregates["average_latency_ms"] or 0),
        "total_tokens": aggregates["total_tokens"] or 0,
        "success_rate": round((successful / volume) * 100, 1) if volume else 0,
    }
