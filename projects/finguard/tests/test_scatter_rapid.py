"""Tests for the scatter-gather and rapid-movement detectors (M3).

Hand-built canonical frames — no dataset required. A detected motif is a
suspicious pattern, never a laundering finding; these tests validate
detector mechanics only.
"""

from __future__ import annotations

import pandas as pd
import pytest

from finguard.graph import detect_rapid_movement, detect_scatter_gather


def _frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """Canonical minimal frame from ``(sender, receiver, amount)`` rows,
    one transfer per hour starting 2022-09-01 00:00."""
    stamps = pd.date_range("2022-09-01 00:00", periods=len(rows), freq="1h")
    return pd.DataFrame(
        {
            "tx_id": list(range(1, len(rows) + 1)),
            "timestamp": stamps,
            "from_account": [r[0] for r in rows],
            "to_account": [r[1] for r in rows],
            "amount_received": [r[2] for r in rows],
            "receiving_currency": "US Dollar",
            "amount_paid": [r[2] for r in rows],
            "payment_currency": "US Dollar",
            "payment_format": "ACH",
            "from_bank": 1,
            "to_bank": 2,
            "is_laundering": 0,
        }
    )


class TestScatterGather:
    def test_hub_detected(self) -> None:
        rows = [(f"S{i}", "HUB", 100.0 + i) for i in range(4)]  # 4 sources in
        rows += [("HUB", f"K{i}", 90.0 + i) for i in range(4)]  # 4 sinks out
        alerts = detect_scatter_gather(_frame(rows), min_sources=4, min_sinks=4)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.typology == "scatter_gather"
        assert alert.account == "HUB"
        assert alert.score["distinct_sources"] == 4
        assert alert.score["distinct_sinks"] == 4
        assert alert.score["total_in"] == pytest.approx(100 + 101 + 102 + 103)
        assert len(alert.tx_ids) == 8

    def test_no_outgoing_leg_no_alert(self) -> None:
        rows = [(f"S{i}", "HUB", 100.0) for i in range(4)]  # converges, never redistributes
        assert detect_scatter_gather(_frame(rows), min_sources=4, min_sinks=4) == []

    def test_below_source_threshold_no_alert(self) -> None:
        rows = [("S0", "HUB", 100.0), ("S1", "HUB", 100.0)]
        rows += [("HUB", f"K{i}", 50.0) for i in range(4)]
        assert detect_scatter_gather(_frame(rows), min_sources=4, min_sinks=4) == []

    def test_out_of_window_redistribution_ignored(self) -> None:
        rows = [(f"S{i}", "HUB", 100.0) for i in range(4)]
        # Sinks arrive 30 days after the incoming burst - far outside the
        # default 3-day redistribution window.
        late = pd.date_range("2022-09-30 00:00", periods=4, freq="1h")
        frame = _frame(rows)
        extra = pd.DataFrame(
            {
                "tx_id": [5, 6, 7, 8],
                "timestamp": late,
                "from_account": "HUB",
                "to_account": [f"K{i}" for i in range(4)],
                "amount_received": 50.0,
                "receiving_currency": "US Dollar",
                "amount_paid": 50.0,
                "payment_currency": "US Dollar",
                "payment_format": "ACH",
                "from_bank": 1,
                "to_bank": 2,
                "is_laundering": 0,
            }
        )
        combined = pd.concat([frame, extra], ignore_index=True).sort_values(
            "timestamp", kind="mergesort"
        )
        assert detect_scatter_gather(combined, min_sources=4, min_sinks=4) == []


class TestRapidMovement:
    def test_chain_detected(self) -> None:
        # A -> B -> C -> D with 90% pass-through and 1 h gaps.
        rows = [("A", "B", 1000.0), ("B", "C", 900.0), ("C", "D", 800.0)]
        alerts = detect_rapid_movement(_frame(rows), min_hops=3, max_gap=pd.Timedelta(hours=6))
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.typology == "rapid_movement"
        assert alert.account == "A"
        assert alert.counter_account == "D"
        assert alert.score["hops"] == 3
        assert alert.tx_ids == (1, 2, 3)

    def test_gap_too_long_no_alert(self) -> None:
        rows = [("A", "B", 1000.0), ("B", "C", 900.0), ("C", "D", 800.0)]
        frame = _frame(rows)
        # Push hops 2 and 3 days apart - beyond the 6 h gap.
        frame.loc[1, "timestamp"] += pd.Timedelta(days=1)
        frame.loc[2, "timestamp"] += pd.Timedelta(days=2)
        assert detect_rapid_movement(frame, min_hops=3, max_gap=pd.Timedelta(hours=6)) == []

    def test_amount_shrinks_below_pass_through_no_alert(self) -> None:
        rows = [("A", "B", 1000.0), ("B", "C", 100.0), ("C", "D", 90.0)]
        alerts = detect_rapid_movement(
            _frame(rows), min_hops=3, min_pass_through=0.5, max_gap=pd.Timedelta(hours=6)
        )
        assert alerts == []

    def test_shorter_chain_not_alerted_when_min_hops_higher(self) -> None:
        rows = [("A", "B", 100.0), ("B", "C", 90.0)]
        assert detect_rapid_movement(_frame(rows), min_hops=3, max_gap=pd.Timedelta(hours=6)) == []

    def test_alert_cap_and_flag(self) -> None:
        # Dense star-of-chains: A1..A3 -> B -> C each forms a 2-hop chain;
        # with min_hops=2 and max_alerts=2 the cap must engage.
        rows = [(f"A{i}", "B", 100.0 + i) for i in range(3)]
        rows += [("B", "C", 95.0) for _ in range(3)]
        alerts = detect_rapid_movement(_frame(rows), min_hops=2, max_alerts=2)
        assert len(alerts) == 2
        assert any(a.score.get("capped") for a in alerts)

    def test_time_order_enforced(self) -> None:
        # A -> B -> C is only 2 hops; the only 3rd hop candidate (C -> B) is
        # stamped BEFORE the chain starts, so a 3-hop chain must not form.
        rows = [("A", "B", 1000.0), ("B", "C", 900.0), ("C", "B", 850.0)]
        frame = _frame(rows)
        frame.loc[2, "timestamp"] = pd.Timestamp("2022-08-31 23:00")  # before row 0
        alerts = detect_rapid_movement(frame, min_hops=3, max_gap=pd.Timedelta(hours=6))
        assert alerts == []
