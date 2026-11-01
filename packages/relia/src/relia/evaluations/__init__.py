"""Evaluation abstractions: datasets, deterministic checks, runner, results.

The schema layer (``relia.evaluations.base``, protected interface) defines
the shared result shape. ``checks``, ``datasets`` and ``runner`` implement
deterministic evaluation; LLM-as-judge scoring is a separate planned runner
and deliberately never mixes into these metrics.
"""

from relia.evaluations.base import (
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalMetric,
    EvalResult,
)
from relia.evaluations.checks import (
    ContainsCheck,
    DeterministicCheck,
    ExactMatch,
    RegexCheck,
    ValidJsonCheck,
)
from relia.evaluations.datasets import EvalDatasetError, load_eval_dataset
from relia.evaluations.runner import AnswerFn, EvalRunner

__all__ = [
    "AnswerFn",
    "CaseResult",
    "ContainsCheck",
    "DeterministicCheck",
    "EvalCase",
    "EvalDataset",
    "EvalDatasetError",
    "EvalMetric",
    "EvalResult",
    "EvalRunner",
    "ExactMatch",
    "RegexCheck",
    "ValidJsonCheck",
    "load_eval_dataset",
]
