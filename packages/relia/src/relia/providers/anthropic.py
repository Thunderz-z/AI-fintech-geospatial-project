"""Anthropic (Claude) Messages-API provider adapter.

Second implemented wire protocol, for ``https://api.anthropic.com/v1`` and
Anthropic-compatible gateways. Builds
:class:`~relia.providers.anthropic.AnthropicProvider` on the shared HTTP
base (retries, backoff, timeouts, ledger, cost accounting — see
:mod:`relia.providers._http_base`).

Stated limitations (not hidden):

* **Structured outputs are instruction-based.** The Messages API has no
  ``response_format``-style schema parameter in the basic protocol, so when
  ``request.response_schema`` is set, the schema is sent as a system
  instruction and the response is validated client-side with
  ``jsonschema`` — the RELIA contract. A model that ignores the
  instruction fails loudly as ``MalformedStructuredOutputError``; it cannot
  pass silently. Server-side tool-use-based enforcement is not implemented.
* **Roles**: ``system`` messages are extracted to the top-level ``system``
  field; ``user``/``assistant`` pass through; any other role (e.g.
  ``tool``) raises :class:`ProviderError` — tool use is not implemented.
  Anthropic's alternation rules are not silently "fixed": a malformed
  message list surfaces the API's error as-is.
* ``max_tokens`` is mandatory in the Messages API: resolution order is
  ``request.max_output_tokens`` → ``config.default_max_output_tokens`` →
  the documented 1024 fallback.
* A response without a text content block or without a ``usage`` block
  raises :class:`ProviderError` (usage integrity beats tolerance).
* ``529`` (Anthropic "overloaded") is retryable alongside 408/429/5xx;
  the ``retry-after`` header is not honored — backoff stays deterministic.
"""

from __future__ import annotations

import json
from typing import Any

from relia.providers._http_base import BaseHTTPProvider
from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    ProviderError,
    Usage,
)

__all__ = ["ANTHROPIC_VERSION", "AnthropicProvider"]

#: Protocol version header required by the Messages API.
ANTHROPIC_VERSION = "2023-06-01"

_DEFAULT_MAX_TOKENS = 1024

#: Anthropic-specific transient statuses: 529 = "overloaded_error".
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504, 529})

_STRUCTURED_INSTRUCTION = (
    "Respond with a single JSON object and nothing else — no markdown "
    "fences, no prose. The object must validate against this JSON Schema: "
    "{schema}"
)


class AnthropicProvider(BaseHTTPProvider):
    """Adapter for the Anthropic Messages API (Claude models)."""

    retryable_status_codes = _RETRYABLE_STATUS_CODES

    def _endpoint_path(self) -> str:
        return "messages"

    def _request_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._config.api_key.get_secret_value(),
            "anthropic-version": ANTHROPIC_VERSION,
        }

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        chat_messages: list[dict[str, str]] = []
        for message in request.messages:
            if message.role == "system":
                system_parts.append(message.content)
            elif message.role in ("user", "assistant"):
                chat_messages.append(
                    {"role": message.role, "content": message.content}
                )
            else:
                raise ProviderError(
                    f"Message role {message.role!r} is not supported by the "
                    "Anthropic adapter (system messages are extracted; tool "
                    "use is not implemented)."
                )
        if not chat_messages:
            raise ProviderError(
                "Anthropic requires at least one user/assistant message."
            )

        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": (
                request.max_output_tokens
                or self._config.default_max_output_tokens
                or _DEFAULT_MAX_TOKENS
            ),
            "messages": chat_messages,
            "temperature": request.temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.response_schema is not None:
            instruction = _STRUCTURED_INSTRUCTION.format(
                schema=json.dumps(request.response_schema)
            )
            payload["system"] = (
                payload.get("system", "") + "\n\n" + instruction
            ).strip()
        return payload

    def _parse_success(
        self, data: dict[str, Any], request: CompletionRequest
    ) -> CompletionResponse:
        content_blocks = data.get("content")
        if not isinstance(content_blocks, list):
            raise ProviderError("Anthropic response has no content blocks.")
        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            raise ProviderError(
                "Anthropic response contains no text content (tool-use or "
                "empty responses are not supported by this adapter)."
            )

        usage_raw = data.get("usage")
        if not isinstance(usage_raw, dict):
            raise ProviderError(
                "Anthropic response does not report usage; refusing to "
                "record a completion with unknown token consumption."
            )
        try:
            usage = Usage(
                input_tokens=int(usage_raw["input_tokens"]),
                output_tokens=int(usage_raw["output_tokens"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"Anthropic usage block is malformed: {usage_raw!r}"
            ) from exc

        return self._make_response(text=text, usage=usage, data=data, request=request)
