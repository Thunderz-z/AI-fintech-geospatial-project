"""OpenAI-compatible provider adapter (chat-completions wire protocol).

One of two implemented wire protocols — the other is the Anthropic Messages
API in :mod:`relia.providers.anthropic`. Works against any endpoint that
speaks OpenAI chat completions: OpenAI, Grok/xAI, Azure OpenAI, Groq,
DeepSeek, vLLM, OpenRouter, ... For named vendors use the presets in
:mod:`relia.providers.presets` (``claude`` / ``grok`` / ``custom``) instead
of hand-building this class.

Stated limitations (not hidden):

* The wire format sends ``max_tokens`` (widest compatibility across
  OpenAI-compatible servers). Servers that only accept
  ``max_completion_tokens`` for newer models need a config switch once a real
  key/endpoint exists — deliberately not built ahead of that.
* A 2xx response without a ``usage`` block raises :class:`ProviderError`
  instead of silently zeroing the accounting; usage integrity beats
  tolerance here.
* Structured outputs are validated client-side with ``jsonschema`` even when
  the server also enforces ``response_format``: the client-side check is the
  contract, server enforcement is only an optimization.
* Retries use exponential backoff **without jitter** — the schedule is
  deterministic and the sleep callable is injectable, which keeps tests
  fast and reproducible. Jitter would help under thundering-herd load; add
  it only when a real endpoint shows that problem.
"""

from __future__ import annotations

from typing import Any

from relia.providers._http_base import BaseHTTPProvider
from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ProviderError,
    Usage,
)
from relia.providers.config import ENV_PREFIX, ProviderConfig, UsageLedger

__all__ = ["ENV_PREFIX", "OpenAICompatibleProvider", "ProviderConfig", "UsageLedger"]

#: HTTP statuses considered transient and safe to retry with backoff.
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class OpenAICompatibleProvider(BaseHTTPProvider):
    """Adapter for OpenAI-compatible chat-completions endpoints.

    See :class:`~relia.providers._http_base.BaseHTTPProvider` for the shared
    constructor arguments (``http_client`` for mock transports, injectable
    ``sleep`` for retry tests).
    """

    retryable_status_codes = _RETRYABLE_STATUS_CODES

    def _endpoint_path(self) -> str:
        return "chat/completions"

    def _request_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.api_key.get_secret_value()}"
        }

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
        }
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        return payload

    def _parse_success(
        self, data: dict[str, Any], request: CompletionRequest
    ) -> CompletionResponse:
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise ProviderError("Provider response contains no choices.")
        content = (choices[0].get("message") or {}).get("content")
        if not isinstance(content, str):
            raise ProviderError(
                "Provider response has no text content (tool-call or empty "
                "responses are not supported by this adapter)."
            )

        usage_raw = data.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderError(
                "Provider response does not report usage; refusing to record "
                "a completion with unknown token consumption."
            )
        try:
            usage = Usage(
                input_tokens=int(usage_raw["prompt_tokens"]),
                output_tokens=int(usage_raw["completion_tokens"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"Provider usage block is malformed: {usage_raw!r}"
            ) from exc

        return self._make_response(text=content, usage=usage, data=data, request=request)
