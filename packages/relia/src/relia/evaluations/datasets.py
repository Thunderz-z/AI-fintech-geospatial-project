"""Eval-dataset loading from TOML files (stdlib ``tomllib`` — no new deps).

Format::

    dataset_id = "water-summary-smoke"
    version = "1.0.0"

    [[cases]]
    input = "Summarize the 2026 winter water dynamics."
    expected = "..."           # optional; needed by expected-based checks
    case_id = "w-1"            # optional; defaults to a generated id

    [cases.context]
    region = "Ramsar IN2481"
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from relia.evaluations.base import EvalCase, EvalDataset
from relia.providers.base import ReliaError

__all__ = ["EvalDatasetError", "load_eval_dataset"]


class EvalDatasetError(ReliaError):
    """An evaluation dataset file is missing, malformed or incomplete."""


def load_eval_dataset(path: str | Path) -> EvalDataset:
    """Load an :class:`EvalDataset` from a TOML file."""
    path = Path(path)
    try:
        data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvalDatasetError(f"Cannot read eval dataset {path}: {exc}") from exc

    try:
        cases_raw = data.pop("cases")
        return EvalDataset(
            dataset_id=data.pop("dataset_id"),
            version=data.pop("version"),
            cases=[EvalCase.model_validate(case) for case in cases_raw],
        )
    except KeyError as exc:
        raise EvalDatasetError(
            f"Eval dataset {path} is missing required key {exc.args[0]!r} "
            "(needs dataset_id, version, cases)."
        ) from exc
    except Exception as exc:  # pydantic ValidationError or wrong shapes
        raise EvalDatasetError(
            f"Eval dataset {path} is malformed: {exc}"
        ) from exc
