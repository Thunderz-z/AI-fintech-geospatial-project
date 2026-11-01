"""RELIA — shared AI reliability, evaluation and evidence-contract infrastructure.

RELIA is the reusable foundation shared by the portfolio applications
(TerraScope, FinGuard). It provides the LLM provider abstraction, tracing,
evaluation tooling, record/replay cassettes, regression analysis and the typed
evidence contracts that make generated claims machine-verifiable.

Status: M2 service layer implemented: configuration/data-path utilities
(``relia.config``), evidence contracts (``relia.contracts``), the provider
abstraction with two wire protocols — OpenAI-compatible and Anthropic
Messages API — plus named presets (``claude`` / ``grok`` / ``custom`` /
``openai-compatible``) and the scripted test double (``relia.providers``),
record/replay cassettes (``relia.replay``), the versioned prompt registry
(``relia.prompts``), deterministic evaluation (``relia.evaluations``) and
the ``relia`` CLI (``relia eval run/compare``). LLM-as-judge scoring,
retrieval evaluation, regression bisection and the tracing exporter are
designed but not implemented — see ``docs/architecture/relia.md`` and
``docs/decisions/``.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
