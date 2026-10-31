"""Provider abstraction for LLM access.

Defines the core protocol and transport-agnostic DTOs. Concrete provider
adapters (hosted LLM APIs) are planned — see ``docs/architecture/relia.md``.
The protocol is intentionally small: chat-style completion with optional
structured-output schema, explicit timeouts and usage accounting.
"""

from relia.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    MalformedStructuredOutputError,
    Message,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ReliaError,
    Usage,
)

__all__ = [
    "CompletionRequest",
    "CompletionResponse",
    "LLMProvider",
    "MalformedStructuredOutputError",
    "Message",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ReliaError",
    "Usage",
]
