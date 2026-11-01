"""Parse an IBM AML ``*_Patterns.txt`` ground-truth file into a DataFrame.

Each laundering attempt is delimited by::

    BEGIN LAUNDERING ATTEMPT - <TYPE>[...]
    <transaction rows, same 11-column schema as the Trans CSV>
    END LAUNDERING ATTEMPT - <TYPE>[...]

The parser returns one row per attempt with its type and the set of
transaction keys ``(from_account, to_account, timestamp)`` of its member
rows, usable as detector ground truth.
"""

from __future__ import annotations

import re

import pandas as pd

__all__ = ["parse_patterns_file"]

_BEGIN = re.compile(r"^BEGIN LAUNDERING ATTEMPT - ([A-Z-]+)")
_END = re.compile(r"^END LAUNDERING ATTEMPT")


def parse_patterns_file(path: str) -> pd.DataFrame:
    """Parse *path* into ``(attempt_id, typology, tx_keys)`` rows.

    ``tx_keys`` is a Python ``set`` of ``(from_account, to_account,
    Timestamp)`` tuples — the join key against canonical transactions
    (``from_account``, ``to_account``, ``timestamp``).
    """
    text = open(path, encoding="utf-8").read()
    attempts: list[dict] = []
    typology: str | None = None
    keys: set[tuple[str, str, pd.Timestamp]] = set()
    attempt_id = 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        begin = _BEGIN.match(line)
        if begin:
            typology = begin.group(1).lower().replace("-", "_")
            keys = set()
            continue
        if _END.match(line):
            if typology is not None and keys:
                attempts.append(
                    {
                        "attempt_id": attempt_id,
                        "typology": typology,
                        "tx_keys": keys,
                        "n_transactions": len(keys),
                    }
                )
                attempt_id += 1
            typology, keys = None, set()
            continue
        if typology is not None:
            parts = line.split(",")
            if len(parts) >= 5:
                ts = pd.to_datetime(parts[0], format="%Y/%m/%d %H:%M")
                keys.add((parts[2].strip(), parts[4].strip(), ts))

    return pd.DataFrame(attempts, columns=["attempt_id", "typology", "tx_keys", "n_transactions"])
