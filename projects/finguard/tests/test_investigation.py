"""Tests for the investigation queue and audit log (finguard.investigation)."""

import json
from pathlib import Path

import pytest

from finguard.investigation import (
    Decision,
    InvestigationError,
    InvestigationQueue,
    QueuePaths,
)


@pytest.fixture()
def queue(tmp_path: Path) -> InvestigationQueue:
    paths = QueuePaths(
        state=tmp_path / "investigation" / "queue_state.json",
        audit=tmp_path / "investigation" / "audit_log.jsonl",
    )
    return InvestigationQueue(paths)


def _alert(queue: InvestigationQueue, account: str = "HUB", rank: float | None = 0.9):
    return queue.enqueue(
        typology="fan_in",
        account=account,
        tx_ids=(1, 2, 3, 4),
        score={"distinct_senders": 4},
        rank=rank,
        evidence_claim_id="claim-123",
    )


class TestEnqueue:
    def test_enqueue_persists_and_audits(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        assert record.status == "open"
        assert queue.paths.state.is_file() and queue.paths.audit.is_file()
        events = queue.audit_events()
        assert len(events) == 1
        assert events[0]["event"] == "enqueue"
        assert events[0]["alert_id"] == record.alert_id

    def test_ranked_ordering(self, queue: InvestigationQueue) -> None:
        low = _alert(queue, account="LOW", rank=0.1)
        high = _alert(queue, account="HIGH", rank=0.99)
        unranked = _alert(queue, account="UNRANKED", rank=None)
        ordered = [r.account for r in queue.list_all()]
        assert ordered == ["HIGH", "LOW", "UNRANKED"]
        assert queue.list_all(status="open")[0].alert_id == high.alert_id
        assert unranked.rank is None and low.rank == 0.1


class TestDecide:
    def test_dismiss_flow(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        decided = queue.decide(
            record.alert_id, Decision.DISMISS, decided_by="analyst-7", notes="benign payroll"
        )
        assert decided.status == "dismissed"
        assert decided.decided_by == "analyst-7"
        events = queue.audit_events()
        assert [e["event"] for e in events] == ["enqueue", "decision"]
        assert events[1]["detail"]["action"] == "dismiss"

    def test_requires_named_human(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        with pytest.raises(InvestigationError, match="named human"):
            queue.decide(record.alert_id, Decision.CLOSE, decided_by="  ")

    def test_escalation_requires_notes(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        with pytest.raises(InvestigationError, match="notes"):
            queue.decide(record.alert_id, Decision.ESCALATE, decided_by="analyst-7")
        decided = queue.decide(
            record.alert_id, Decision.ESCALATE, decided_by="analyst-7", notes="structuring-like"
        )
        assert decided.status == "escalated"

    def test_double_decision_rejected(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        queue.decide(record.alert_id, Decision.CLOSE, decided_by="analyst-7")
        with pytest.raises(InvestigationError, match="already decided"):
            queue.decide(record.alert_id, Decision.CLOSE, decided_by="analyst-8")

    def test_unknown_alert(self, queue: InvestigationQueue) -> None:
        with pytest.raises(InvestigationError, match="Unknown alert"):
            queue.decide("nope", Decision.CLOSE, decided_by="analyst-7")

    def test_invalid_action_rejected(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        with pytest.raises(ValueError):
            queue.decide(record.alert_id, "auto-close", decided_by="analyst-7")


class TestPersistence:
    def test_round_trip_rebuild(self, tmp_path: Path) -> None:
        paths = QueuePaths(
            state=tmp_path / "inv" / "queue_state.json",
            audit=tmp_path / "inv" / "audit_log.jsonl",
        )
        first = InvestigationQueue(paths)
        record = _alert(first)
        first.decide(record.alert_id, Decision.CLOSE, decided_by="analyst-7")

        reopened = InvestigationQueue(paths)
        assert len(reopened.list_all()) == 1
        assert reopened.list_all()[0].status == "closed"
        assert len(reopened.audit_events()) == 2

    def test_audit_log_is_append_only_jsonl(self, queue: InvestigationQueue) -> None:
        record = _alert(queue)
        queue.decide(record.alert_id, Decision.DISMISS, decided_by="analyst-7")
        raw = queue.paths.audit.read_text(encoding="utf-8").splitlines()
        assert len(raw) == 2
        for line in raw:
            assert set(json.loads(line)) == {"ts", "event", "alert_id", "actor", "detail"}


class TestNoAutonomousDecisions:
    def test_no_auto_decision_surface(self) -> None:
        # Governance: the module must not expose any way to decide without
        # a named human. Assert the decision path signature requires it.
        import inspect

        signature = inspect.signature(InvestigationQueue.decide)
        assert "decided_by" in signature.parameters
        assert signature.parameters["decided_by"].default is inspect.Parameter.empty
