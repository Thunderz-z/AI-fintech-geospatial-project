"""Cost and token accounting across provider calls (observability).

Thread-safe accumulator fed by :class:`relia.providers.base.CompletionResponse`
instances; snapshots are exportable per service run. Prices are the
provider's own ``cost_usd`` when present — RELIA never invents prices.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import asdict, dataclass

from relia.providers.base import CompletionResponse

__all__ = ["CostLedger", "CostSnapshot"]

_UTC = dt.UTC


@dataclass
class CostSnapshot:
    """Totals at one point in time."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None while any call lacked a price
    by_model: dict[str, dict[str, float]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.by_model is None:
            self.by_model = {}

    def to_dict(self) -> dict:
        return asdict(self)


class CostLedger:
    """Accumulate usage and cost from completion responses (thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls = 0
        self._input_tokens = 0
        self._output_tokens = 0
        self._cost_known = 0.0
        self._cost_unknown = 0
        self._by_model: dict[str, dict[str, float]] = {}

    def add(self, response: CompletionResponse) -> None:
        with self._lock:
            self._calls += 1
            self._input_tokens += response.usage.input_tokens
            self._output_tokens += response.usage.output_tokens
            bucket = self._by_model.setdefault(
                f"{response.provider}/{response.model}",
                {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += 1
            bucket["input_tokens"] += response.usage.input_tokens
            bucket["output_tokens"] += response.usage.output_tokens
            if response.cost_usd is not None:
                self._cost_known += response.cost_usd
                bucket["cost_usd"] += response.cost_usd
            else:
                self._cost_unknown += 1

    def snapshot(self) -> CostSnapshot:
        with self._lock:
            return CostSnapshot(
                calls=self._calls,
                input_tokens=self._input_tokens,
                output_tokens=self._output_tokens,
                cost_usd=round(self._cost_known, 6) if self._cost_unknown == 0 else None,
                by_model={
                    model: {key: round(value, 6) for key, value in bucket.items()}
                    for model, bucket in self._by_model.items()
                },
            )
