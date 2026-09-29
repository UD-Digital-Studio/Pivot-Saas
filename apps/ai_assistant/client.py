import logging
from dataclasses import dataclass

import requests
from django.conf import settings

from .exceptions import (
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
    OpenRouterRateLimitError,
    OpenRouterResponseError,
    OpenRouterServiceError,
    OpenRouterTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    model: str
    finish_reason: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class OpenRouterClient:
    """Small OpenRouter client isolated from views and business permissions."""

    def __init__(self, *, session=None):
        self.session = session or requests.Session()

    def complete(self, *, messages, model=None, max_tokens=None, temperature=None):
        self._validate_configuration()
        payload = {
            "model": model or settings.OPENROUTER_MODEL,
            "messages": self._validated_messages(messages),
            "max_tokens": max_tokens or settings.OPENROUTER_MAX_TOKENS,
            "temperature": (
                settings.OPENROUTER_TEMPERATURE if temperature is None else temperature
            ),
            "stream": False,
        }
        try:
            response = self.session.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=(
                    settings.OPENROUTER_CONNECT_TIMEOUT,
                    settings.OPENROUTER_READ_TIMEOUT,
                ),
            )
        except requests.Timeout as exc:
            logger.warning("OpenRouter timeout", extra={"provider": "openrouter"})
            raise OpenRouterTimeoutError from exc
        except requests.RequestException as exc:
            logger.warning(
                "OpenRouter transport failure",
                extra={"provider": "openrouter", "error_type": type(exc).__name__},
            )
            raise OpenRouterServiceError from exc

        if response.status_code in {401, 403}:
            logger.error(
                "OpenRouter authentication rejected",
                extra={"status": response.status_code},
            )
            raise OpenRouterAuthenticationError
        if response.status_code == 429:
            logger.warning("OpenRouter rate limited", extra={"status": response.status_code})
            raise OpenRouterRateLimitError
        if response.status_code >= 500:
            logger.warning("OpenRouter unavailable", extra={"status": response.status_code})
            raise OpenRouterServiceError
        if response.status_code >= 400:
            logger.warning("OpenRouter request rejected", extra={"status": response.status_code})
            raise OpenRouterResponseError

        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty completion")
            usage = data.get("usage") or {}
            return ChatCompletion(
                content=content.strip(),
                model=str(data.get("model") or payload["model"]),
                finish_reason=str(choice.get("finish_reason") or ""),
                prompt_tokens=self._optional_int(usage.get("prompt_tokens")),
                completion_tokens=self._optional_int(usage.get("completion_tokens")),
                total_tokens=self._optional_int(usage.get("total_tokens")),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Invalid OpenRouter response", extra={"status": response.status_code})
            raise OpenRouterResponseError from exc

    @staticmethod
    def _validated_messages(messages):
        if not isinstance(messages, (list, tuple)) or not messages:
            raise ValueError("messages must be a non-empty list")
        validated = []
        for message in messages:
            if not isinstance(message, dict):
                raise ValueError("each message must be a dictionary")
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError("unsupported message role")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("message content must not be empty")
            validated.append({"role": role, "content": content.strip()})
        return validated

    @staticmethod
    def _optional_int(value):
        return value if isinstance(value, int) else None

    @staticmethod
    def _validate_configuration():
        if not settings.OPENROUTER_API_KEY or not settings.OPENROUTER_MODEL:
            raise OpenRouterConfigurationError
        if not settings.OPENROUTER_BASE_URL.startswith("https://"):
            raise OpenRouterConfigurationError

    @staticmethod
    def _headers():
        return {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "HTTP-Referer": settings.OPENROUTER_SITE_URL,
            "X-OpenRouter-Title": settings.OPENROUTER_APP_TITLE,
        }
