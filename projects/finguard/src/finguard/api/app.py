"""FinGuard investigation API (FastAPI).

The human-in-the-loop surface: list ranked alerts, inspect their evidence
bundles, and record human decisions (every decision is audited by
:class:`finguard.investigation.InvestigationQueue`). There is deliberately
**no autonomous decision endpoint** — consequential dispositions require a
named reviewer (AGENTS.md rule 7, architecture/finguard.md governance).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from finguard.investigation import (
    Decision,
    InvestigationError,
    InvestigationQueue,
    QueuePaths,
)
from relia.config.paths import DataRootError


class DecisionRequest(BaseModel):
    """A human decision on one alert."""

    action: Decision
    decided_by: str = Field(min_length=1, description="Named human reviewer")
    notes: str = Field(default="", description="Justification (required for escalate)")


def _resolve_root(data_root: Path | None) -> Path:
    if data_root is not None:
        return data_root
    try:
        from relia.config.paths import get_data_root

        return get_data_root() / "finguard"
    except DataRootError as exc:
        raise HTTPException(status_code=503, detail=f"Dataset root unavailable: {exc}") from exc


def create_app(
    queue_paths: QueuePaths | None = None,
    *,
    data_root: Path | None = None,
) -> FastAPI:
    """Build the API; injections keep tests offline and hermetic."""

    def queue_dep() -> InvestigationQueue:
        try:
            return InvestigationQueue(queue_paths)
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=f"Queue unavailable: {exc}") from exc

    app = FastAPI(
        title="FinGuard Investigation API",
        description=(
            "Alert queue over synthetic-data detections. A detected motif is a "
            "suspicious pattern, never a finding of money laundering; every "
            "consequential decision requires a named human reviewer."
        ),
        version="0.1.0",
    )

    @app.get("/health")
    def health(queue: InvestigationQueue = Depends(queue_dep)) -> dict[str, Any]:
        return {
            "status": "ok",
            "open_alerts": len(queue.list_all(status="open")),
            "data_root": str(_resolve_root(data_root)),
        }

    @app.get("/alerts")
    def alerts(
        queue: InvestigationQueue = Depends(queue_dep),
        status: Literal["open", "dismissed", "escalated", "closed"] | None = None,
    ) -> dict[str, Any]:
        records = queue.list_all(status=status)
        return {
            "count": len(records),
            "alerts": [record.to_dict() for record in records],
            "note": "ranked by score where available; patterns, not findings",
        }

    @app.get("/alerts/{alert_id}")
    def alert_detail(
        alert_id: str,
        queue: InvestigationQueue = Depends(queue_dep),
    ) -> dict[str, Any]:
        for record in queue.list_all():
            if record.alert_id == alert_id:
                return record.to_dict()
        raise HTTPException(status_code=404, detail=f"Unknown alert {alert_id!r}")

    @app.get("/alerts/{alert_id}/evidence")
    def alert_evidence(
        alert_id: str,
        queue: InvestigationQueue = Depends(queue_dep),
    ) -> dict[str, Any]:
        for record in queue.list_all():
            if record.alert_id == alert_id:
                break
        else:
            raise HTTPException(status_code=404, detail=f"Unknown alert {alert_id!r}")
        if not record.evidence_claim_id:
            raise HTTPException(status_code=404, detail="Alert carries no evidence contract")
        root = _resolve_root(data_root)
        for line in (root / "processed" / "alert-evidence.jsonl").read_text(
            encoding="utf-8"
        ).splitlines():
            if not line.strip():
                continue
            contract = json.loads(line)
            if contract.get("claim_id") == record.evidence_claim_id:
                return contract
        raise HTTPException(
            status_code=404,
            detail=f"Evidence contract {record.evidence_claim_id!r} not in the bundle",
        )

    @app.post("/alerts/{alert_id}/decision")
    def decide(
        alert_id: str,
        request: DecisionRequest,
        queue: InvestigationQueue = Depends(queue_dep),
    ) -> dict[str, Any]:
        try:
            record = queue.decide(
                alert_id,
                request.action,
                decided_by=request.decided_by,
                notes=request.notes,
            )
        except InvestigationError as exc:
            message = str(exc)
            code = 404 if "Unknown alert" in message else 409
            raise HTTPException(status_code=code, detail=message) from exc
        return record.to_dict()

    @app.get("/audit")
    def audit(queue: InvestigationQueue = Depends(queue_dep)) -> dict[str, Any]:
        events = queue.audit_events()
        return {"count": len(events), "events": events}

    return app


app = create_app()
