from unittest.mock import Mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.ai_assistant.client import OpenRouterClient
from apps.ai_assistant.exceptions import (
    OpenRouterAuthenticationError,
    OpenRouterConfigurationError,
    OpenRouterRateLimitError,
    OpenRouterResponseError,
    OpenRouterServiceError,
    OpenRouterTimeoutError,
)

BASE_SETTINGS = {
    "OPENROUTER_API_KEY": "test-key-never-real",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENROUTER_MODEL": "openrouter/auto",
    "OPENROUTER_CONNECT_TIMEOUT": 3,
    "OPENROUTER_READ_TIMEOUT": 20,
    "OPENROUTER_MAX_TOKENS": 600,
    "OPENROUTER_TEMPERATURE": 0.2,
    "OPENROUTER_SITE_URL": "https://pivot.example.test",
    "OPENROUTER_APP_TITLE": "PIVOT Engineering",
}


@override_settings(**BASE_SETTINGS)
class OpenRouterClientTests(SimpleTestCase):
    def setUp(self):
        self.session = Mock()
        self.client = OpenRouterClient(session=self.session)

    def response(self, status=200, payload=None):
        response = Mock(status_code=status)
        response.json.return_value = payload
        self.session.post.return_value = response
        return response

    def test_success_returns_normalized_completion_and_safe_request(self):
        self.response(
            payload={
                "model": "provider/model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "  Bonjour  "},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
            }
        )

        result = self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])

        self.assertEqual(result.content, "Bonjour")
        self.assertEqual(result.total_tokens, 14)
        call = self.session.post.call_args
        self.assertEqual(call.kwargs["timeout"], (3, 20))
        self.assertEqual(call.kwargs["headers"]["Authorization"], "Bearer test-key-never-real")
        self.assertEqual(call.kwargs["headers"]["X-OpenRouter-Title"], "PIVOT Engineering")
        self.assertNotIn("test-key-never-real", str(call.kwargs["json"]))

    @override_settings(OPENROUTER_API_KEY="")
    def test_missing_key_fails_before_network_call(self):
        with self.assertRaises(OpenRouterConfigurationError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])
        self.session.post.assert_not_called()

    def test_timeout_is_normalized(self):
        self.session.post.side_effect = requests.ReadTimeout("secret provider details")
        with self.assertRaises(OpenRouterTimeoutError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])

    def test_transport_failure_is_normalized(self):
        self.session.post.side_effect = requests.ConnectionError("secret provider details")
        with self.assertRaises(OpenRouterServiceError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])

    def test_authentication_and_rate_limit_are_normalized(self):
        self.response(status=401, payload={"error": {"message": "do not expose"}})
        with self.assertRaises(OpenRouterAuthenticationError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])
        self.response(status=429, payload={"error": {"message": "do not expose"}})
        with self.assertRaises(OpenRouterRateLimitError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])

    def test_invalid_success_payload_is_rejected(self):
        self.response(payload={"choices": []})
        with self.assertRaises(OpenRouterResponseError):
            self.client.complete(messages=[{"role": "user", "content": "Bonjour"}])

    def test_invalid_message_is_rejected_before_network_call(self):
        with self.assertRaises(ValueError):
            self.client.complete(messages=[{"role": "tool", "content": "No"}])
        self.session.post.assert_not_called()
