"""Synthetic transaction generator with planted AML typologies (test fixtures).

**Synthetic data only.** Everything produced here is fabricated for testing
and detector calibration. A planted motif is a known suspicious *pattern*
used to measure detector precision — it is never a finding of money
laundering, and any result computed on this data must be labelled synthetic
(AGENTS.md rules 5/7, ADR-0006).

The output frame uses the canonical FinGuard schema (see
:mod:`finguard.schema`) so fixtures exercise the exact validation path the
real IBM AML data will take. Alongside the frame, the generator returns a
:class:`PlantedMotif` index recording which ``tx_id`` values belong to which
planted typology — that index is the ground truth motif-detector tests
measure against (M1 step 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from finguard.schema import CANONICAL_COLUMNS, validate_transactions

__all__ = [
    "PlantedMotif",
    "TYPOLOGIES",
    "generate_synthetic_transactions",
]

Typology = Literal["fan_in", "fan_out", "structuring", "cycle", "scatter_gather"]

#: Planted typologies supported by the generator.
TYPOLOGIES: tuple[Typology, ...] = (
    "fan_in",
    "fan_out",
    "structuring",
    "cycle",
    "scatter_gather",
)

_PAYMENT_FORMATS = ("ACH", "Wire", "Cheque", "Credit Card", "Cash", "Reinvestment")
_CURRENCIES = ("US Dollar", "Euro", "Yuan", "Yen", "Ruble", "UK Pound")

_MOTIF_ID_COL = "_motif_id"


@dataclass(frozen=True)
class PlantedMotif:
    """Ground-truth record for one planted typology instance."""

    motif_id: str
    typology: Typology
    tx_ids: tuple[int, ...]
    accounts: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _hex_accounts(rng: np.random.Generator, n: int, exclude: set[str]) -> list[str]:
    """Draw *n* distinct IBM-style 8-hex account IDs not in *exclude*."""
    chosen: list[str] = []
    while len(chosen) < n:
        candidate = f"{rng.integers(16**7, 16**8):08X}"
        if candidate not in exclude and candidate not in chosen:
            chosen.append(candidate)
    return chosen


def _background_rows(
    rng: np.random.Generator, n: int, start: pd.Timestamp, days: int
) -> pd.DataFrame:
    """Vectorized legitimate background traffic over the time window."""
    minutes = pd.date_range(start, periods=days * 24 * 60, freq="min")
    ids = rng.integers(16**7, 16**8, size=n)
    sender_ids = rng.integers(16**7, 16**8, size=n)
    return pd.DataFrame(
        {
            "timestamp": rng.choice(minutes, size=n),
            "from_bank": rng.integers(0, 40, size=n),
            "from_account": [f"{v:08X}" for v in sender_ids],
            "to_bank": rng.integers(0, 40, size=n),
            "to_account": [f"{v:08X}" for v in ids],
            "amount_received": np.round(rng.lognormal(6.0, 1.5, size=n), 2),
            "receiving_currency": rng.choice(_CURRENCIES, size=n),
            "amount_paid": np.round(rng.lognormal(6.0, 1.5, size=n), 2),
            "payment_currency": rng.choice(_CURRENCIES, size=n),
            "payment_format": rng.choice(_PAYMENT_FORMATS, size=n),
            "is_laundering": np.zeros(n, dtype="int64"),
        }
    )


def _motif_rows(
    rng: np.random.Generator,
    typology: Typology,
    motif_id: str,
    start: pd.Timestamp,
    days: int,
    degree: int,
    structuring_threshold: float,
) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    """Build one planted typology instance; every row is flagged laundering."""
    used: set[str] = set()
    # Motif offsets spread over at most 5 days (cycle); keep the base far
    # enough from the window end that every planted row stays inside it.
    span_minutes = days * 24 * 60
    margin_minutes = min(5 * 24 * 60 + 1, span_minutes // 2)
    base_ts = start + pd.Timedelta(
        minutes=int(rng.integers(0, max(1, span_minutes - margin_minutes)))
    )
    bank = int(rng.integers(0, 40))
    currency = str(rng.choice(_CURRENCIES))
    fmt = str(rng.choice(("ACH", "Wire")))
    degree = max(2, degree)  # every typology needs at least 2 participants

    if typology in ("fan_in", "fan_out"):
        if typology == "fan_in":
            senders = _hex_accounts(rng, degree, used)
            receiver = _hex_accounts(rng, 1, used | set(senders))[0]
            src, dst = senders, [receiver] * degree
            roles = {"senders": tuple(senders), "collector": receiver}
        else:
            distributor = _hex_accounts(rng, 1, used)[0]
            receivers = _hex_accounts(rng, degree, used | {distributor})
            src, dst = [distributor] * degree, receivers
            roles = {"distributor": distributor, "receivers": tuple(receivers)}
        amounts = np.round(rng.uniform(1_000.0, 50_000.0, size=degree), 2)
        timestamps = base_ts + pd.to_timedelta(
            rng.integers(0, 3 * 24 * 60, size=degree), unit="min"
        )

    elif typology == "structuring":
        # One sender -> one receiver, many transfers just below the reporting
        # threshold, inside a short window (classic smurfing shape).
        sender, receiver = _hex_accounts(rng, 2, used)
        amounts = np.round(
            structuring_threshold - rng.uniform(1.0, 500.0, size=degree), 2
        )
        timestamps = base_ts + pd.to_timedelta(
            rng.integers(0, 2 * 24 * 60, size=degree), unit="min"
        )
        src, dst = [sender] * degree, [receiver] * degree
        roles = {"sender": sender, "receiver": receiver}

    elif typology == "cycle":
        # Same amount circulating through a ring of accounts back to origin.
        members = _hex_accounts(rng, degree, used)
        shared_amount = round(float(rng.uniform(10_000.0, 100_000.0)), 2)
        amounts = np.full(degree, shared_amount)
        timestamps = base_ts + pd.to_timedelta(
            np.sort(rng.integers(0, 5 * 24 * 60, size=degree)), unit="min"
        )
        src, dst = members, members[1:] + members[:1]
        roles = {"members": tuple(members)}

    else:  # scatter_gather: degree senders -> hub -> degree receivers
        senders = _hex_accounts(rng, degree, used)
        hub = _hex_accounts(rng, 1, used | set(senders))[0]
        receivers = _hex_accounts(rng, degree, used | set(senders) | {hub})
        gather_amounts = np.round(
            rng.uniform(5_000.0, 50_000.0, size=degree), 2
        )
        scatter_amounts = np.full(degree, round(float(gather_amounts.sum() / degree), 2))
        gather_ts = base_ts + pd.to_timedelta(
            rng.integers(0, 2 * 24 * 60, size=degree), unit="min"
        )
        scatter_ts = base_ts + pd.to_timedelta(
            2 * 24 * 60 + rng.integers(0, 2 * 24 * 60, size=degree), unit="min"
        )
        src = senders + [hub] * degree
        dst = [hub] * degree + receivers
        amounts = np.concatenate([gather_amounts, scatter_amounts])
        timestamps = pd.DatetimeIndex(gather_ts).append(pd.DatetimeIndex(scatter_ts))
        roles = {"senders": tuple(senders), "hub": hub, "receivers": tuple(receivers)}

    n = len(src)
    frame = pd.DataFrame(
        {
            _MOTIF_ID_COL: motif_id,
            "timestamp": timestamps,
            "from_bank": np.full(n, bank, dtype="int64"),
            "from_account": src,
            "to_bank": np.full(n, bank, dtype="int64"),
            "to_account": dst,
            "amount_received": amounts,
            "receiving_currency": currency,
            "amount_paid": amounts,
            "payment_currency": currency,
            "payment_format": fmt,
            "is_laundering": np.ones(n, dtype="int64"),
        }
    )
    return frame, roles


def generate_synthetic_transactions(
    *,
    n_normal: int = 5_000,
    typologies: tuple[Typology, ...] = ("fan_in", "fan_out", "structuring"),
    motif_degree: int = 6,
    structuring_threshold: float = 10_000.0,
    start: str = "2022-09-01",
    days: int = 10,
    seed: int = 42,
) -> tuple[pd.DataFrame, list[PlantedMotif]]:
    """Generate a synthetic transaction frame with planted AML typologies.

    Args:
        n_normal: Number of legitimate background transactions.
        typologies: One planted motif instance per entry.
        motif_degree: Participants per motif (fan-in/out arms, structuring
            transfers, cycle length).
        structuring_threshold: Amounts planted by the ``structuring`` typology
            stay just below this reporting threshold.
        start: Window start date (inclusive).
        days: Window length in days.
        seed: Deterministic seed.

    Returns:
        ``(transactions, motifs)`` where ``transactions`` is a validated
        canonical-schema frame sorted by ``timestamp`` with sequential
        ``tx_id``, and ``motifs`` records each planted instance's ``tx_ids``
        (ground truth for motif-detector precision) and participant accounts.

    Raises:
        ValueError: If an unknown typology is requested.
    """
    unknown = [t for t in typologies if t not in TYPOLOGIES]
    if unknown:
        raise ValueError(f"Unknown typologies: {unknown}; supported: {TYPOLOGIES}")

    rng = np.random.default_rng(seed)
    start_ts = pd.Timestamp(start)
    background = _background_rows(rng, n_normal, start_ts, days).assign(
        **{_MOTIF_ID_COL: None}
    )

    parts: list[pd.DataFrame] = [background]
    planted: list[tuple[str, Typology, dict[str, tuple[str, ...]]]] = []
    for i, typology in enumerate(typologies):
        motif_id = f"{typology}-{i}"
        motif_rows, roles = _motif_rows(
            rng,
            typology,
            motif_id=motif_id,
            start=start_ts,
            days=days,
            degree=motif_degree,
            structuring_threshold=structuring_threshold,
        )
        parts.append(motif_rows)
        planted.append((motif_id, typology, roles))

    combined = pd.concat(parts, ignore_index=True)
    combined = combined.sort_values("timestamp", kind="mergesort").reset_index(drop=True)
    combined["tx_id"] = pd.RangeIndex(len(combined), dtype="int64")
    transactions = validate_transactions(combined)

    motifs: list[PlantedMotif] = []
    for motif_id, typology, roles in planted:
        ids = tuple(
            int(t)
            for t in combined.loc[combined[_MOTIF_ID_COL] == motif_id, "tx_id"]
        )
        motifs.append(
            PlantedMotif(
                motif_id=motif_id, typology=typology, tx_ids=ids, accounts=roles
            )
        )

    return transactions[list(CANONICAL_COLUMNS)], motifs
