import hashlib
import hmac
import re
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from .models import AssistantRequest


class AssistantSecurityError(Exception):
    user_message = "Cette demande ne peut pas être traitée."
    status_code = 400


class PromptInjectionBlocked(AssistantSecurityError):
    user_message = "Je ne peux pas suivre des instructions qui contournent la sécurité de PIVOT."


class AssistantRateLimited(AssistantSecurityError):
    user_message = "Vous avez envoyé trop de demandes. Réessayez dans quelques instants."
    status_code = 429


class AssistantRequestInProgress(AssistantSecurityError):
    user_message = "Une réponse est déjà en cours de préparation. Patientez un instant."
    status_code = 409


class AssistantDuplicateRequest(AssistantSecurityError):
    user_message = "Cette même demande vient déjà d’être traitée."
    status_code = 409


INJECTION_PATTERNS = (
    r"\b(ignore|oublie|forget|disregard)\b.{0,40}\b(instruction|instructions|prompt|règle|rules|system)\b",
    (
        r"\b(révèle|affiche|montre|reveal|show|print|repeat)\b.{0,40}"
        r"\b(prompt|instruction système|system instruction|secret|clé api|api key)\b"
    ),
    r"\b(exécute|execute|run)\b.{0,30}\b(sql|commande|command|shell|python|code)\b",
    r"\b(contourne|désactive|bypass|disable)\b.{0,30}\b(sécurité|security|permission|autorisation|filtre|filter)\b",
    r"\b(developer mode|mode développeur|jailbreak|dan mode)\b",
)


def request_fingerprint(content):
    normalized = " ".join(str(content or "").casefold().split()).encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), normalized, digestmod=hashlib.sha256
    ).hexdigest()


def detect_prompt_injection(content):
    normalized = " ".join(str(content or "").casefold().split())
    return any(
        re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in INJECTION_PATTERNS
    )


def begin_assistant_request(*, user, conversation, content):
    now = timezone.now()
    fingerprint = request_fingerprint(content)
    stale_before = now - timedelta(seconds=settings.AI_REQUEST_STALE_SECONDS)
    AssistantRequest.objects.filter(
        user=user,
        status=AssistantRequest.Status.PROCESSING,
        created_at__lt=stale_before,
    ).update(
        status=AssistantRequest.Status.FAILED,
        error_code="stale_request",
        completed_at=now,
    )
    window_start = now - timedelta(seconds=settings.AI_RATE_LIMIT_WINDOW_SECONDS)
    if (
        AssistantRequest.objects.filter(user=user, created_at__gte=window_start).count()
        >= settings.AI_RATE_LIMIT_REQUESTS
    ):
        raise AssistantRateLimited
    consumed_tokens = (
        AssistantRequest.objects.filter(
            user=user,
            created_at__gte=window_start,
            status=AssistantRequest.Status.SUCCESS,
        ).aggregate(total=Sum("total_tokens"))["total"]
        or 0
    )
    if consumed_tokens >= settings.AI_TOKEN_BUDGET_PER_WINDOW:
        raise AssistantRateLimited
    if AssistantRequest.objects.filter(
        user=user, status=AssistantRequest.Status.PROCESSING
    ).exists():
        raise AssistantRequestInProgress
    duplicate_start = now - timedelta(seconds=settings.AI_DUPLICATE_WINDOW_SECONDS)
    if AssistantRequest.objects.filter(
        user=user,
        request_hash=fingerprint,
        created_at__gte=duplicate_start,
        status__in=(AssistantRequest.Status.PROCESSING, AssistantRequest.Status.SUCCESS),
    ).exists():
        raise AssistantDuplicateRequest
    if detect_prompt_injection(content):
        AssistantRequest.objects.create(
            organization=user.organization,
            user=user,
            conversation=conversation,
            request_hash=fingerprint,
            status=AssistantRequest.Status.BLOCKED,
            error_code="prompt_injection",
            completed_at=now,
        )
        raise PromptInjectionBlocked
    try:
        with transaction.atomic():
            request_record = AssistantRequest.objects.create(
                organization=user.organization,
                user=user,
                conversation=conversation,
                request_hash=fingerprint,
            )
    except IntegrityError as exc:
        raise AssistantRequestInProgress from exc
    request_record._started_monotonic = time.monotonic()
    return request_record


def _latency_ms(request_record):
    started = getattr(request_record, "_started_monotonic", None)
    if started is None:
        return None
    return max(0, round((time.monotonic() - started) * 1000))


def complete_assistant_request(request_record, completion):
    request_record.status = AssistantRequest.Status.SUCCESS
    request_record.prompt_tokens = completion.prompt_tokens
    request_record.completion_tokens = completion.completion_tokens
    request_record.total_tokens = completion.total_tokens
    request_record.latency_ms = _latency_ms(request_record)
    request_record.completed_at = timezone.now()
    request_record.save(
        update_fields=(
            "status",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "latency_ms",
            "completed_at",
        )
    )


def fail_assistant_request(request_record, error):
    request_record.status = AssistantRequest.Status.FAILED
    request_record.error_code = type(error).__name__[:64]
    request_record.latency_ms = _latency_ms(request_record)
    request_record.completed_at = timezone.now()
    request_record.save(update_fields=("status", "error_code", "latency_ms", "completed_at"))
