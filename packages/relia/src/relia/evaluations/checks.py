"""Deterministic evaluation checks — no LLM judging in this module.

Every check here is a pure function of (case, answer) producing a score, so
results are exactly reproducible. LLM-as-judge scoring is a separate,
planned runner; mixing the two in one metric would make the deterministic
signal unfalsifiable-by-inspection and the judge signal unauditable.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from relia.evaluations.base import EvalCase

__all__ = [
    "ContainsCheck",
    "DeterministicCheck",
    "ExactMatch",
    "RegexCheck",
    "ValidJsonCheck",
]


class DeterministicCheck(Protocol):
    """One deterministic per-case scoring function."""

    name: str
    #: Checks that read ``case.expected`` must declare it; the runner
    #: validates up-front that the dataset supports them.
    requires_expected: bool

    def score(self, case: EvalCase, answer: str) -> float:
        """Score one answer in [0.0, 1.0]; must be a pure function."""
        ...


class ExactMatch:
    """1.0 iff the stripped answer equals the stripped expected string."""

    name = "exact_match"
    requires_expected = True

    def score(self, case: EvalCase, answer: str) -> float:
        if case.expected is None:
            return 0.0
        return 1.0 if answer.strip() == case.expected.strip() else 0.0


class ContainsCheck:
    """1.0 iff the answer contains the given substring (default: case-insensitive)."""

    requires_expected = False

    def __init__(self, substring: str, *, case_sensitive: bool = False) -> None:
        self.substring = substring
        self.case_sensitive = case_sensitive
        self.name = f"contains({substring!r})"

    def score(self, case: EvalCase, answer: str) -> float:
        haystack, needle = answer, self.substring
        if not self.case_sensitive:
            haystack, needle = haystack.lower(), needle.lower()
        return 1.0 if needle in haystack else 0.0


class RegexCheck:
    """1.0 iff the answer matches the regular expression (``re.search``)."""

    requires_expected = False

    def __init__(self, pattern: str, *, flags: int = 0) -> None:
        self.pattern = pattern
        self._compiled = re.compile(pattern, flags)
        self.name = f"regex({pattern!r})"

    def score(self, case: EvalCase, answer: str) -> float:
        return 1.0 if self._compiled.search(answer) else 0.0


class ValidJsonCheck:
    """1.0 iff the answer parses as JSON (any JSON value)."""

    name = "valid_json"
    requires_expected = False

    def score(self, case: EvalCase, answer: str) -> float:
        try:
            json.loads(answer)
        except json.JSONDecodeError:
            return 0.0
        return 1.0
