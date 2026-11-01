"""Provider abstractions: core protocol, DTOs and error hierarchy.

Concrete provider adapters (hosted LLM APIs) implement
:class:`LLMProvider`; provider-specific details (auth, wire formats,
retry policies) stay in the adapter, never in callers.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ReliaError(Exception):
    """Base class for all RELIA errors."""


class ProviderError(ReliaError):
    """A provider request failed (network, auth, quota, server error)."""


class ProviderTimeoutError(ProviderError):
    """The provider did not answer within the configured timeout."""


class ProviderRateLimitError(ProviderError):
    """The provider signalled rate limiting; safe to retry with backoff."""


class MalformedStructuredOutputError(ProviderError):
    """The provider response did not satisfy the requested output schema."""


class Message(BaseModel):
    """One chat message in a completion request."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class CompletionRequest(BaseModel):
    """A single chat-completion request, provider-agnostic."""

    model: str = Field(min_length=1)
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float = Field(default=60.0, gt=0.0)
    response_schema: dict[str, Any] | None = Field(
        default=None,
        description="JSON-Schema-style contract the response must satisfy, if any.",
    )


class Usage(BaseModel):
    """Token accounting for one completion."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class CompletionResponse(BaseModel):
    """A normalized completion result with usage and provenance."""

    text: str
    structured: dict[str, Any] | None = None
    model: str
    provider: str
    usage: Usage
    request_id: str | None = None
    cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Cost of this completion in USD at the provider's configured rates, "
            "computed at request time; None when no price information is configured. "
            "Frozen at request time by design: later price-sheet changes do not "
            "rewrite historical responses."
        ),
    )


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal provider surface; concrete adapters implement this protocol."""

    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute one completion request."""
        ...
