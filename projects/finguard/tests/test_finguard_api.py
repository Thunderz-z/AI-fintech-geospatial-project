"""API tests for FinGuard's investigation surface (hermetic via injections)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finguard.api.app import create_app
from finguard.investigation import InvestigationQueue, QueuePaths


@pytest.fixture()
def queue_paths(tmp_path: Path) -> QueuePaths:
    return QueuePaths(
        state=tmp_path / "inv" / "queue_state.json",
        audit=tmp_path / "inv" / "audit_log.jsonl",
    )


@pytest.fixture()
def seeded(queue_paths: QueuePaths, tmp_path: Path) -> tuple[QueuePaths, Path]:
    queue = InvestigationQueue(queue_paths)
    ranked = queue.enqueue(
        typology="fan_in",
        account="HUB1",
        tx_ids=(1, 2, 3, 4),
        score={"distinct_senders": 4},
        rank=0.91,
        evidence_claim_id="claim-ranked",
    )
    queue.enqueue(
        typology="cycle",
        account="RING",
        tx_ids=(11, 12, 13),
        score={"ring_length": 3},
        rank=0.42,
    )
    assert ranked.alert_id  # sanity for readers
    # Evidence bundle under a separate injected data root: <root>/processed/alert-evidence.jsonl
    evidence_root = tmp_path / "finguard-root"
    processed = evidence_root / "processed"
    processed.mkdir(parents=True)
    (processed / "HI-Small_alert-evidence.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "claim_id": "claim-ranked",
                "claim_text": "Fan-in convergence on HUB1 (suspicious pattern).",
            }
        )
        + "\n"
        + json.dumps({"schema_version": "1.0.0", "claim_id": "other", "claim_text": "x"})
        + "\n",
        encoding="utf-8",
    )
    return queue_paths, evidence_root


@pytest.fixture()
def client(seeded: tuple[QueuePaths, Path]) -> TestClient:
    paths, data_root = seeded
    return TestClient(create_app(paths, data_root=data_root))


def test_health(client: TestClient) -> None:
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["open_alerts"] == 2


def test_alerts_ranked_order(client: TestClient) -> None:
    payload = client.get("/alerts").json()
    assert payload["count"] == 2
    assert payload["alerts"][0]["account"] == "HUB1"
    assert payload["note"].endswith("patterns, not findings")


def test_status_filter(client: TestClient) -> None:
    payload = client.get("/alerts", params={"status": "open"}).json()
    assert payload["count"] == 2
    assert client.get("/alerts", params={"status": "closed"}).json()["count"] == 0


def test_decision_flow_and_audit(client: TestClient) -> None:
    alerts = client.get("/alerts").json()["alerts"]
    alert_id = alerts[0]["alert_id"]

    decided = client.post(
        f"/alerts/{alert_id}/decision",
        json={"action": "escalate", "decided_by": "analyst-7", "notes": "matches planted profile"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "escalated"

    audit = client.get("/audit").json()
    assert audit["count"] == 3  # 2 enqueues + 1 decision
    assert audit["events"][-1]["detail"]["action"] == "escalate"

    # Decisions are final -> second attempt is a 409.
    conflict = client.post(
        f"/alerts/{alert_id}/decision",
        json={"action": "dismiss", "decided_by": "analyst-8"},
    )
    assert conflict.status_code == 409


def test_escalation_without_notes_rejected(client: TestClient) -> None:
    alert_id = client.get("/alerts").json()["alerts"][0]["alert_id"]
    response = client.post(
        f"/alerts/{alert_id}/decision",
        json={"action": "escalate", "decided_by": "analyst-7"},
    )
    assert response.status_code == 409
    assert "notes" in response.json()["detail"]


def test_anonymous_decision_rejected(client: TestClient) -> None:
    alert_id = client.get("/alerts").json()["alerts"][0]["alert_id"]
    response = client.post(
        f"/alerts/{alert_id}/decision",
        json={"action": "close", "decided_by": ""},
    )
    assert response.status_code == 422  # pydantic min_length guard


def test_evidence_endpoint_matches_claim(client: TestClient) -> None:
    alerts = client.get("/alerts").json()["alerts"]
    ranked_id = alerts[0]["alert_id"]
    payload = client.get(f"/alerts/{ranked_id}/evidence").json()
    assert payload["claim_id"] == "claim-ranked"
    assert payload["claim_text"].endswith("suspicious pattern).")


def test_evidence_missing_contract_404(client: TestClient) -> None:
    alerts = client.get("/alerts").json()["alerts"]
    unranked = alerts[1]["alert_id"]  # no evidence_claim_id
    assert client.get(f"/alerts/{unranked}/evidence").status_code == 404


def test_unknown_alert_404(client: TestClient) -> None:
    assert client.get("/alerts/missing").status_code == 404
    response = client.post(
        "/alerts/missing/decision",
        json={"action": "close", "decided_by": "analyst-7"},
    )
    assert response.status_code == 404
