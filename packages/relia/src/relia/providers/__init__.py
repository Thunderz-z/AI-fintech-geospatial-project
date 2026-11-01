"""Provider abstraction for LLM access.

Core protocol and transport-agnostic DTOs live in ``relia.providers.base``
(protected interface). Concrete implementations: the OpenAI-compatible
adapter (:mod:`relia.providers.openai_compat`) and the scripted test double
(:mod:`relia.providers.fake`).
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
from relia.providers.fake import ScriptedProvider, scripted_response
from relia.providers.openai_compat import (
    OpenAICompatibleProvider,
    ProviderConfig,
    UsageLedger,
)

__all__ = [
    "CompletionRequest",
    "CompletionResponse",
    "LLMProvider",
    "MalformedStructuredOutputError",
    "Message",
    "OpenAICompatibleProvider",
    "ProviderConfig",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ReliaError",
    "ScriptedProvider",
    "Usage",
    "UsageLedger",
    "scripted_response",
]
