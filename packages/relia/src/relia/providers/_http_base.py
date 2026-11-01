"""Shared HTTP plumbing for wire-protocol provider adapters (internal).

``BaseHTTPProvider`` owns everything that is identical across adapters: the
retry loop with deterministic exponential backoff, timeout and
transport-error mapping, non-retryable client errors, non-JSON body
handling, the usage ledger, cost accounting and request building.

Subclasses implement the wire protocol through four hooks plus a class
attribute:

* ``retryable_status_codes`` — statuses worth retrying (vendor-specific,
  e.g. Anthropic adds 529 "overloaded")
* ``_endpoint_path()`` — path appended to the configured base URL
* ``_request_headers()`` — auth + protocol headers
* ``_build_payload(request)`` — protocol request body
* ``_parse_success(data, request)`` — protocol response body →
  :class:`CompletionResponse` (via :meth:`_make_response` so ledger and
  cost accounting stay uniform)

The underscore hooks are internal to the providers package; callers only
see the ``LLMProvider`` protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from relia.providers.config import (
    ProviderConfig,
    UsageLedger,
    _compute_cost_usd,
    _validate_structured,
)


class BaseHTTPProvider:
    """HTTP transport with retries; the wire protocol is supplied by hooks."""

    retryable_status_codes: frozenset[int] = frozenset()

    def __init__(
        self,
        config: ProviderConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._sleep = sleep
        self._client = http_client or httpx.AsyncClient(
            timeout=config.request_timeout_seconds
        )
        self._owns_client = http_client is None
        self.ledger = UsageLedger()

    @property
    def name(self) -> str:
        return self._config.provider_name

    @property
    def config(self) -> ProviderConfig:
        return self._config

    async def aclose(self) -> None:
        """Close the internally owned HTTP client (injected clients are not closed)."""
        if self._owns_client:
            await self._client.aclose()

    def build_request(
        self,
        messages: Sequence[Message | tuple[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
        response_schema: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> CompletionRequest:
        """Build a :class:`CompletionRequest` using the configured defaults.

        ``messages`` accepts :class:`Message` objects or ``(role, content)``
        tuples. The model comes from the explicit argument or the configured
        ``default_model``; with neither, construction fails loudly.
        """
        resolved_model = model or self._config.default_model
        if not resolved_model:
            raise ProviderError(
                "No model given and no default_model configured for provider "
                f"{self.name!r}."
            )
        return CompletionRequest(
            model=resolved_model,
            messages=[
                m if isinstance(m, Message) else Message(role=m[0], content=m[1])
                for m in messages
            ],
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            response_schema=response_schema,
            timeout_seconds=timeout_seconds
            or self._config.request_timeout_seconds,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one completion with retries on transient failures."""
        payload = self._build_payload(request)
        url = f"{self._config.base_url.rstrip('/')}/{self._endpoint_path()}"
        headers = self._request_headers()

        last_error: ProviderError | None = None
        for attempt in range(self._config.max_retries + 1):
            if attempt > 0:
                await self._sleep(self._backoff_delay(attempt - 1))
            result = await self._attempt(url, headers, payload, request)
            if isinstance(result, CompletionResponse):
                return result
            last_error = result
        assert last_error is not None
        raise last_error

    def _backoff_delay(self, retry_index: int) -> float:
        """Exponential backoff, capped; no jitter (see openai_compat notes)."""
        delay = self._config.retry_backoff_seconds * (2**retry_index)
        return min(delay, self._config.retry_backoff_max_seconds)

    async def _attempt(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        request: CompletionRequest,
    ) -> CompletionResponse | ProviderError:
        """One HTTP attempt. Returns the parsed response or the error to retry/raise."""
        try:
            response = await self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=request.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            return ProviderTimeoutError(
                f"Provider timed out after {request.timeout_seconds}s: {exc}"
            )
        except httpx.TransportError as exc:
            return ProviderError(f"Transport failure talking to provider: {exc}")

        if response.status_code in self.retryable_status_codes:
            return self._error_for_status(response)
        if response.status_code >= 400:
            raise self._error_for_status(response)  # non-retryable client error
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"Provider returned non-JSON body (HTTP {response.status_code})."
            ) from exc
        return self._parse_success(data, request)

    def _error_for_status(self, response: httpx.Response) -> ProviderError:
        body = response.text[:500]
        if response.status_code == 429:
            return ProviderRateLimitError(
                f"Provider rate limit hit (HTTP 429): {body}"
            )
        return ProviderError(
            f"Provider returned HTTP {response.status_code}: {body}"
        )

    def _make_response(
        self,
        *,
        text: str,
        usage: Any,
        data: dict[str, Any],
        request: CompletionRequest,
    ) -> CompletionResponse:
        """Assemble the final response.

        Structured-output validation (client-side, the RELIA contract) and
        cost accounting + ledger recording happen here uniformly for every
        wire protocol.
        """
        structured = (
            _validate_structured(text, request.response_schema)
            if request.response_schema is not None
            else None
        )
        completion = CompletionResponse(
            text=text,
            structured=structured,
            model=str(data.get("model", request.model)),
            provider=self.name,
            usage=usage,
            request_id=data.get("id"),
            cost_usd=_compute_cost_usd(self._config, usage),
        )
        self.ledger.record(completion)
        return completion

    # --- wire-protocol hooks (implemented by subclasses) ---

    def _endpoint_path(self) -> str:
        raise NotImplementedError

    def _request_headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        raise NotImplementedError

    def _parse_success(
        self, data: dict[str, Any], request: CompletionRequest
    ) -> CompletionResponse:
        raise NotImplementedError
