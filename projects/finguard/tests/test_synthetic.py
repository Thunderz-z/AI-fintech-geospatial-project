"""Synthetic generator tests: planted typologies must be exactly recoverable."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from finguard.schema import CANONICAL_COLUMNS
from finguard.synthetic import generate_synthetic_transactions

EXPECTED_MOTIF_ROWS = {
    "fan_in": 6,
    "fan_out": 6,
    "structuring": 6,
    "cycle": 6,
    "scatter_gather": 12,  # gather arm + scatter arm
}


@pytest.fixture
def generated():
    transactions, motifs = generate_synthetic_transactions(
        n_normal=800,
        typologies=("fan_in", "fan_out", "structuring", "cycle", "scatter_gather"),
        motif_degree=6,
        seed=11,
    )
    return transactions, motifs


def test_output_is_canonical_and_validated(generated) -> None:
    transactions, motifs = generated

    assert list(transactions.columns) == list(CANONICAL_COLUMNS)
    assert transactions["tx_id"].is_unique
    assert transactions["timestamp"].is_monotonic_increasing
    # Every motif's tx_ids must reference real, flagged rows.
    for motif in motifs:
        rows = transactions.loc[transactions["tx_id"].isin(motif.tx_ids)]
        assert len(rows) == len(motif.tx_ids)
        assert (rows["is_laundering"] == 1).all()


def test_planted_row_counts_are_exact(generated) -> None:
    transactions, motifs = generated

    expected_total = 800 + sum(EXPECTED_MOTIF_ROWS.values())
    assert len(transactions) == expected_total
    assert int(transactions["is_laundering"].sum()) == sum(EXPECTED_MOTIF_ROWS.values())
    assert len(transactions.loc[transactions["is_laundering"] == 0]) == 800
    for motif in motifs:
        assert len(motif.tx_ids) == EXPECTED_MOTIF_ROWS[motif.typology]


def test_motif_shapes(generated) -> None:
    transactions, motifs = generated
    by_id = {m.motif_id: m for m in motifs}
    rows = transactions.set_index("tx_id")

    fan_in = rows.loc[list(by_id["fan_in-0"].tx_ids)]
    assert fan_in["to_account"].nunique() == 1
    assert fan_in["from_account"].nunique() == 6
    assert fan_in["to_account"].iloc[0] == by_id["fan_in-0"].accounts["collector"]

    fan_out = rows.loc[list(by_id["fan_out-1"].tx_ids)]
    assert fan_out["from_account"].nunique() == 1
    assert fan_out["to_account"].nunique() == 6
    assert fan_out["from_account"].iloc[0] == by_id["fan_out-1"].accounts["distributor"]

    structuring = rows.loc[list(by_id["structuring-2"].tx_ids)]
    assert (structuring["amount_paid"] < 10_000.0).all()
    assert structuring["from_account"].nunique() == 1
    assert structuring["to_account"].nunique() == 1

    cycle = rows.loc[list(by_id["cycle-3"].tx_ids)]
    assert cycle["amount_paid"].nunique() == 1  # same amount circulates
    members = set(by_id["cycle-3"].accounts["members"])
    assert set(cycle["from_account"]) == members
    assert set(cycle["to_account"]) == members

    scatter = rows.loc[list(by_id["scatter_gather-4"].tx_ids)]
    hub = by_id["scatter_gather-4"].accounts["hub"]
    gather = scatter.loc[scatter["to_account"] == hub]
    scatter_out = scatter.loc[scatter["from_account"] == hub]
    assert len(gather) == 6 and len(scatter_out) == 6
    assert gather["amount_paid"].sum() >= scatter_out["amount_paid"].sum() * 0.99


def test_deterministic_with_same_seed() -> None:
    tx_a, motifs_a = generate_synthetic_transactions(n_normal=100, seed=3)
    tx_b, motifs_b = generate_synthetic_transactions(n_normal=100, seed=3)

    assert_frame_equal(tx_a, tx_b)
    assert [m.tx_ids for m in motifs_a] == [m.tx_ids for m in motifs_b]


def test_different_seeds_differ() -> None:
    tx_a, _ = generate_synthetic_transactions(n_normal=100, seed=3)
    tx_b, _ = generate_synthetic_transactions(n_normal=100, seed=4)

    assert len(tx_a) == len(tx_b)
    assert not tx_a["from_account"].equals(tx_b["from_account"])


def test_unknown_typology_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown typologies"):
        generate_synthetic_transactions(typologies=("smurfing",))  # type: ignore[arg-type]


def test_timestamps_inside_window(generated) -> None:
    transactions, _ = generated

    stamps = transactions["timestamp"]
    assert stamps.min() >= pd.Timestamp("2022-09-01")
    assert stamps.max() < pd.Timestamp("2022-09-11")
