"""RELIA — shared AI reliability, evaluation and evidence-contract infrastructure.

RELIA is the reusable foundation shared by the portfolio applications
(TerraScope, FinGuard). It provides the LLM provider abstraction, tracing,
evaluation tooling, record/replay cassettes, regression analysis and the typed
evidence contracts that make generated claims machine-verifiable.

Status: foundation phase. Implemented surface: configuration/data-path
utilities (``relia.config``), evidence contracts (``relia.contracts``),
core interface definitions (``providers``, ``tracing``, ``evaluations``,
``replay``) and the ``relia`` CLI. Regression analysis and observability
exports are designed but not implemented — see ``docs/architecture/relia.md``
and ``docs/decisions/``.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
