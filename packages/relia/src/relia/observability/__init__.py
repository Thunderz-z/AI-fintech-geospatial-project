"""Observability: structured logging, tracing exporters, cost accounting.

Planned (``docs/architecture/relia.md``):

* Structured logging configuration shared by all services.
* OpenTelemetry exporter wiring behind :class:`relia.tracing.TraceRecorder`.
* Token and cost accounting built on ``relia.providers.base.Usage``.

Not implemented yet.
"""
