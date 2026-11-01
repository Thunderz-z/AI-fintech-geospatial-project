"""Provider abstraction for LLM access.

Core protocol and transport-agnostic DTOs live in ``relia.providers.base``
(protected interface). Implemented adapters behind the shared HTTP base
(:mod:`relia.providers._http_base`): the OpenAI-compatible wire protocol
(:mod:`relia.providers.openai_compat`), the Anthropic Messages API
(:mod:`relia.providers.anthropic`) and named presets
(:mod:`relia.providers.presets` — ``claude``, ``grok``, ``custom``,
``openai-compatible``). :mod:`relia.providers.fake` provides the scripted
test double.
"""

from relia.providers.anthropic import ANTHROPIC_VERSION, AnthropicProvider
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
    ENV_PREFIX,
    OpenAICompatibleProvider,
    ProviderConfig,
    UsageLedger,
)
from relia.providers.presets import (
    PROVIDER_PRESETS,
    ProviderPreset,
    create_provider,
)

__all__ = [
    "ANTHROPIC_VERSION",
    "ENV_PREFIX",
    "LLMProvider",
    "MalformedStructuredOutputError",
    "Message",
    "OpenAICompatibleProvider",
    "PROVIDER_PRESETS",
    "AnthropicProvider",
    "CompletionRequest",
    "CompletionResponse",
    "ProviderConfig",
    "ProviderError",
    "ProviderPreset",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ReliaError",
    "ScriptedProvider",
    "Usage",
    "UsageLedger",
    "create_provider",
    "scripted_response",
]
