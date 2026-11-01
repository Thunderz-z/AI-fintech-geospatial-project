"""Human-in-the-loop investigation queue with an append-only audit log (M3).

Governance rules (architecture/finguard.md, AGENTS.md rule 7):

* A detected motif is a *suspicious pattern*, never a finding of money
  laundering; alerts are candidates for human review only.
* Every consequential decision (dismiss / escalate / close) is taken by a
  named human — there is deliberately **no autonomous decision method**.
* Every mutation appends an immutable event to the audit log (JSONL). The
  audit log is write-only from this module's perspective: state can be
  rebuilt from it, events are never edited or removed.

Queue state persists as JSON beside the audit log; both live under
``<data_root>/finguard/processed/investigation/`` by default.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from relia.config.paths import resolve_project_data_dir

__all__ = [
    "AlertRecord",
    "Decision",
    "InvestigationError",
    "InvestigationQueue",
    "QueuePaths",
]

_AUDIT_FILENAME = "audit_log.jsonl"
_STATE_FILENAME = "queue_state.json"


class InvestigationError(RuntimeError):
    """Raised for invalid investigation operations."""


class Decision(StrEnum):
    """The only consequential dispositions a human may take."""

    DISMISS = "dismiss"
    ESCALATE = "escalate"
    CLOSE = "close"


@dataclass
class AlertRecord:
    """One alert in the review queue with its lifecycle state."""

    alert_id: str
    typology: str
    account: str
    tx_ids: tuple[int, ...]
    score: dict[str, Any]
    rank: float | None = None  # ranker score when the alert was ranked
    evidence_claim_id: str | None = None  # relia EvidenceContract link
    status: str = "open"  # open | dismissed | escalated | closed
    decided_by: str | None = None
    decided_at: str | None = None
    notes: str = ""
    enqueued_at: str = field(
        default_factory=lambda: dt.datetime.now(tz=dt.UTC).isoformat()
    )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["tx_ids"] = list(self.tx_ids)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> AlertRecord:
        data = dict(data)
        data["tx_ids"] = tuple(int(t) for t in data.get("tx_ids", []))
        return cls(**data)


@dataclass(frozen=True)
class QueuePaths:
    """Locations of the queue state and its append-only audit log."""

    state: Path
    audit: Path

    @classmethod
    def default(cls) -> QueuePaths:
        base = resolve_project_data_dir("finguard") / "processed" / "investigation"
        base.mkdir(parents=True, exist_ok=True)
        return cls(state=base / _STATE_FILENAME, audit=base / _AUDIT_FILENAME)


class InvestigationQueue:
    """Persistent alert queue. Every mutation appends to the audit log."""

    def __init__(self, paths: QueuePaths | None = None) -> None:
        self.paths = paths or QueuePaths.default()
        self._alerts: dict[str, AlertRecord] = {}
        if self.paths.state.is_file():
            self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        state = json.loads(self.paths.state.read_text(encoding="utf-8"))
        self._alerts = {
            item["alert_id"]: AlertRecord.from_dict(item)
            for item in state.get("alerts", [])
        }

    def _save(self) -> None:
        self.paths.state.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": dt.datetime.now(tz=dt.UTC).isoformat(),
            "alerts": [record.to_dict() for record in self._alerts.values()],
        }
        self.paths.state.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _audit(self, event: str, alert_id: str, actor: str, detail: dict[str, Any]) -> None:
        entry = {
            "ts": dt.datetime.now(tz=dt.UTC).isoformat(),
            "event": event,
            "alert_id": alert_id,
            "actor": actor,
            "detail": detail,
        }
        self.paths.audit.parent.mkdir(parents=True, exist_ok=True)
        with self.paths.audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    # -- operations --------------------------------------------------------

    def enqueue(
        self,
        *,
        typology: str,
        account: str,
        tx_ids: tuple[int, ...],
        score: dict[str, Any],
        rank: float | None = None,
        evidence_claim_id: str | None = None,
        actor: str = "system",
    ) -> AlertRecord:
        """Add one alert to the queue (system action, not a decision)."""
        record = AlertRecord(
            alert_id=uuid4().hex,
            typology=typology,
            account=account,
            tx_ids=tuple(int(t) for t in tx_ids),
            score=dict(score),
            rank=rank,
            evidence_claim_id=evidence_claim_id,
        )
        self._alerts[record.alert_id] = record
        self._save()
        self._audit(
            "enqueue",
            record.alert_id,
            actor,
            {"typology": typology, "account": account, "rank": rank},
        )
        return record

    def list_all(self, *, status: str | None = None) -> list[AlertRecord]:
        """All records (optionally filtered), ranked score descending."""
        records = list(self._alerts.values())
        if status is not None:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: (-(r.rank if r.rank is not None else -1e18), r.enqueued_at))
        return records

    def decide(
        self,
        alert_id: str,
        action: Decision | str,
        *,
        decided_by: str,
        notes: str = "",
    ) -> AlertRecord:
        """Apply a human decision. ``decided_by`` must name the reviewer.

        Raises:
            InvestigationError: Unknown alert, unknown action, missing
                reviewer identity, double decision, or escalation without
                notes (escalations must justify themselves).
        """
        action = Decision(action)
        if not decided_by or not decided_by.strip():
            raise InvestigationError("A decision requires a named human reviewer.")
        record = self._alerts.get(alert_id)
        if record is None:
            raise InvestigationError(f"Unknown alert {alert_id!r}.")
        if record.status != "open":
            raise InvestigationError(
                f"Alert {alert_id!r} already decided ({record.status}); decisions are final."
            )
        if action is Decision.ESCALATE and not notes.strip():
            raise InvestigationError("Escalation requires notes justifying the escalation.")

        record.status = {
            Decision.DISMISS: "dismissed",
            Decision.ESCALATE: "escalated",
            Decision.CLOSE: "closed",
        }[action]
        record.decided_by = decided_by.strip()
        record.decided_at = dt.datetime.now(tz=dt.UTC).isoformat()
        record.notes = notes.strip()
        self._save()
        self._audit(
            "decision",
            alert_id,
            record.decided_by,
            {"action": action.value, "notes": record.notes, "typology": record.typology},
        )
        return record

    def audit_events(self) -> list[dict[str, Any]]:
        """Read back the audit log (for display; never edited here)."""
        if not self.paths.audit.is_file():
            return []
        return [
            json.loads(line)
            for line in self.paths.audit.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
