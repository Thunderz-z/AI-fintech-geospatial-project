"""Transaction graph construction and AML typology detectors (M1 step 6).

**A detected motif is a suspicious pattern, never a finding of money
laundering** (AGENTS.md rule 7). Every alert produced here is a candidate
for human review, with the transaction evidence attached.

Scale note: full networkx graphs over 5M edges are impractical, so the
detectors run *vectorized on the edge frame* (pandas groupbys over
pre-filtered candidate sets) and :func:`build_transaction_graph` materializes
a real ``networkx.MultiDiGraph`` only for bounded windows (investigation
neighbourhoods, small fixtures, evidence bundles).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

__all__ = [
    "MotifAlert",
    "build_transaction_graph",
    "detect_fan_in",
    "detect_structuring",
]


@dataclass(frozen=True)
class MotifAlert:
    """One detected suspicious pattern with its transaction evidence."""

    typology: str  # "fan_in" | "structuring"
    account: str  # focal account (collector / receiving pair endpoint)
    counter_account: str | None  # for structuring: the repeated counterparty
    tx_ids: tuple[int, ...]
    score: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.tx_ids)


def build_transaction_graph(tx: pd.DataFrame) -> nx.MultiDiGraph:
    """Build a directed multi-edge account graph from canonical transactions.

    Nodes are account IDs; each transaction becomes one edge
    ``from_account -> to_account`` carrying ``tx_id``, ``timestamp``,
    ``amount_received``, ``receiving_currency``, ``amount_paid``,
    ``payment_currency``, ``payment_format``, ``from_bank``, ``to_bank``,
    ``is_laundering``. Intended for bounded windows and fixtures, not the
    full 5M-edge dataset (see module docstring).
    """
    graph = nx.MultiDiGraph()
    for row in tx.itertuples(index=False):
        graph.add_edge(
            row.from_account,
            row.to_account,
            key=row.tx_id,
            tx_id=row.tx_id,
            timestamp=row.timestamp,
            amount_received=row.amount_received,
            receiving_currency=row.receiving_currency,
            amount_paid=row.amount_paid,
            payment_currency=row.payment_currency,
            payment_format=row.payment_format,
            from_bank=row.from_bank,
            to_bank=row.to_bank,
            is_laundering=row.is_laundering,
        )
    return graph


def detect_fan_in(
    tx: pd.DataFrame,
    *,
    min_senders: int = 6,
    window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect fan-in attempts: many distinct senders converge on one account.

    Candidate receivers are pre-filtered by distinct incoming senders
    (``>= min_senders``), then scanned with a sliding time window: an alert
    fires when ``min_senders`` distinct senders reach the receiver within
    ``window``.

    Note: planted IBM fan-ins show *highly varied* amounts (verified against
    HI-Small_Patterns.txt), so no amount-similarity condition is applied.

    Args:
        tx: Canonical transactions.
        min_senders: Distinct senders required inside the window.
        window: Convergence window (default 24 h).

    Returns:
        Alerts sorted by distinct-sender count (strongest first).
    """
    window = window if window is not None else pd.Timedelta(hours=24)
    incoming = tx[["tx_id", "timestamp", "from_account", "to_account"]]

    distinct = incoming.groupby("to_account", observed=True)["from_account"].transform(
        "nunique"
    )
    candidates = incoming.loc[distinct >= min_senders]
    alerts: list[MotifAlert] = []

    for receiver, edges in candidates.groupby("to_account", observed=True, sort=False):
        edges = edges.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
        times = edges["timestamp"].to_numpy()
        senders = edges["from_account"].to_numpy()
        tx_ids = edges["tx_id"].to_numpy()

        best: dict[str, Any] | None = None
        left = 0
        seen: dict[str, int] = {}
        for right in range(len(edges)):
            seen[senders[right]] = seen.get(senders[right], 0) + 1
            while (times[right] - times[left]) > window:
                seen[senders[left]] -= 1
                if seen[senders[left]] == 0:
                    del seen[senders[left]]
                left += 1
            distinct = len(seen)
            if distinct >= min_senders and (
                best is None or distinct > best["distinct"]
            ):
                best = {
                    "distinct": distinct,
                    "tx_ids": tuple(int(t) for t in tx_ids[left : right + 1]),
                    "start": times[left],
                    "end": times[right],
                }
        if best is not None:
            alerts.append(
                MotifAlert(
                    typology="fan_in",
                    account=str(receiver),
                    counter_account=None,
                    tx_ids=best["tx_ids"],
                    score={
                        "distinct_senders": best["distinct"],
                        "window_start": str(best["start"]),
                        "window_end": str(best["end"]),
                        "min_senders": min_senders,
                        "window": str(window),
                    },
                )
            )
        if best is not None:
            alerts.append(
                MotifAlert(
                    typology="fan_in",
                    account=str(receiver),
                    counter_account=None,
                    tx_ids=best["tx_ids"],
                    score={
                        "distinct_senders": best["distinct"],
                        "window_start": str(best["start"]),
                        "window_end": str(best["end"]),
                        "min_senders": min_senders,
                        "window": str(window),
                    },
                )
            )

    alerts.sort(key=lambda a: -a.score["distinct_senders"])
    return alerts


def detect_structuring(
    tx: pd.DataFrame,
    *,
    threshold: float = 10_000.0,
    min_transactions: int = 5,
    window: pd.Timedelta | None = None,
) -> list[MotifAlert]:
    """Detect structuring: repeated just-below-threshold transfers between a
    fixed sender/receiver pair inside a short window.

    Args:
        tx: Canonical transactions.
        threshold: Reporting threshold amounts stay below.
        min_transactions: Sub-threshold transfers between the same pair
            required inside ``window``.
        window: Pairing window (default 24 h).

    Returns:
        One alert per (sender, receiver) pair meeting the criteria, strongest
        (most transfers) first.
    """
    window = window if window is not None else pd.Timedelta(hours=24)
    below = tx.loc[
        (tx["amount_paid"] < threshold)
        & (tx["amount_received"] < threshold),
        ["tx_id", "timestamp", "from_account", "to_account", "amount_paid"],
    ]

    pair_size = below.groupby(["from_account", "to_account"], observed=True)[
        "tx_id"
    ].transform("size")
    pairs = below.loc[pair_size >= min_transactions]

    alerts: list[MotifAlert] = []
    for (sender, receiver), edges in pairs.groupby(
        ["from_account", "to_account"], observed=True, sort=False
    ):
        edges = edges.sort_values("timestamp", kind="mergesort")
        times = edges["timestamp"].to_numpy()
        tx_ids = edges["tx_id"].to_numpy()
        k = min_transactions
        # Sliding stretch of k consecutive pair-transfers within the window.
        gaps = times[k - 1 :] - times[: len(times) - k + 1]
        fits = gaps <= window
        if not fits.any():
            continue
        idx = int(np.argmax(fits))
        window_ids = tuple(int(t) for t in tx_ids[idx : idx + k])
        window_amounts = edges["amount_paid"].to_numpy()[idx : idx + k]
        alerts.append(
            MotifAlert(
                typology="structuring",
                account=str(sender),
                counter_account=str(receiver),
                tx_ids=window_ids,
                score={
                    "transfers": k,
                    "total_amount": float(window_amounts.sum()),
                    "threshold": threshold,
                    "window_start": str(times[idx]),
                    "window_end": str(times[idx + k - 1]),
                    "window": str(window),
                },
            )
        )

    alerts.sort(key=lambda a: -a.score["transfers"])
    return alerts
