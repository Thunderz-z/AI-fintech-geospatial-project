"""Evaluation abstractions: datasets, runners and results.

Deterministic checks and LLM-as-judge scoring are separated by design
(see ``docs/architecture/relia.md``). Concrete evaluation runners are
planned; the models below define the shared result schema so evaluation
outputs are comparable across prompt/configuration versions from day one,
with optional bootstrap confidence intervals on sampled metrics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    """One evaluation input with its expectation and optional context."""

    case_id: str = Field(default_factory=lambda: uuid4().hex)
    input: str = Field(min_length=1)
    expected: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class EvalDataset(BaseModel):
    """A versioned evaluation dataset."""

    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    cases: list[EvalCase] = Field(min_length=1)


class EvalMetric(BaseModel):
    """One measured metric for an evaluation run.

    ``sample_size`` is set (together with the interval bounds) when the
    metric is estimated from a sample and a bootstrap confidence interval
    is reported; it stays ``None`` for exact, deterministic metrics.
    """

    name: str = Field(min_length=1)
    value: float
    higher_is_better: bool = True
    sample_size: int | None = Field(default=None, ge=1)
    ci_lower: float | None = None
    ci_upper: float | None = None


class EvalResult(BaseModel):
    """The outcome of one evaluation run, tied to dataset and config versions."""

    result_id: str = Field(default_factory=lambda: uuid4().hex)
    dataset_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    config_version: str = Field(
        min_length=1,
        description="Prompt/configuration version under test.",
    )
    metrics: list[EvalMetric] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: str | None = None
