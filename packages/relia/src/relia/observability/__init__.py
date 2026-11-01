"""Observability: structured logging, tracing exporters, cost accounting.

Implemented: :class:`relia.tracing.memory.InMemoryTraceRecorder` (spans,
events, errors, JSON export) and :class:`relia.observability.cost.CostLedger`
(token/cost accumulation from provider responses). Planned: OpenTelemetry
collector forwarding and structured-logging presets.
"""

from relia.observability.cost import CostLedger, CostSnapshot

__all__ = ["CostLedger", "CostSnapshot"]
