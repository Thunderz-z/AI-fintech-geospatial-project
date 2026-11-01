"""TerraScope read-only analysis API (FastAPI).

Serves the analysis artefacts produced by the pipelines on the data root —
water-extent series + evidence contracts, epoch change detection and
land-cover classification — without re-running anything. Every response
points at the underlying artefact paths so each number stays traceable
(AGENTS.md documentation-honesty rules; read-only surface, no compute).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query

from relia.config.paths import DataRootError

_LATEST_WATER = "water_extent_2019-04-01_2026-10-31_v1.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"Artefact not found: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Artefact unreadable: {exc}") from exc


def _resolve_root(data_root: Path | None) -> Path:
    if data_root is not None:
        return data_root
    try:
        from terrascope.config import data_dir

        return data_dir()
    except DataRootError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Dataset root unavailable: {exc}",
        ) from exc


def create_app(data_root: Path | None = None) -> FastAPI:
    """Build the API; ``data_root`` injection keeps tests offline."""

    def root_dep() -> Path:
        return _resolve_root(data_root)

    app = FastAPI(
        title="TerraScope API",
        description=(
            "Geospatial environmental intelligence for the Pallikaranai Marsh. "
            "Read-only surface over reproducible analysis artefacts; every "
            "payload carries the artefact path it came from."
        ),
        version="0.1.0",
    )

    @app.get("/health")
    def health(root: Path = Depends(root_dep)) -> dict[str, Any]:
        return {"status": "ok", "data_root": str(root)}

    @app.get("/analysis/water-series")
    def water_series(
        root: Path = Depends(root_dep),
        calibrated: Annotated[bool, Query(description="v1 calibrated series (default)")] = True,
    ) -> dict[str, Any]:
        name = _LATEST_WATER if calibrated else "water_extent_2019-04-01_2026-10-31.json"
        payload = _read_json(root / "processed" / "water-extent" / name)
        payload["_artefact"] = f"processed/water-extent/{name}"
        return payload

    @app.get("/analysis/water-series/evidence")
    def water_series_evidence(
        root: Path = Depends(root_dep),
        calibrated: Annotated[bool, Query()] = True,
    ) -> dict[str, Any]:
        name = (
            "water_extent_2019-04-01_2026-10-31_v1.evidence.json"
            if calibrated
            else "water_extent_2019-04-01_2026-10-31.evidence.json"
        )
        payload = _read_json(root / "processed" / "water-extent" / name)
        payload["_artefact"] = f"processed/water-extent/{name}"
        return payload

    @app.get("/analysis/change")
    def change_detection(
        root: Path = Depends(root_dep),
        epoch_a: str = "winter_2019-20",
        epoch_b: str = "winter",
        season: str = "winter",
    ) -> dict[str, Any]:
        name = f"change_{season}_{epoch_a}_vs_{epoch_b}.json"
        payload = _read_json(root / "processed" / "change-detection" / name)
        payload["_artefact"] = f"processed/change-detection/{name}"
        return payload

    @app.get("/analysis/classification")
    def classification(
        root: Path = Depends(root_dep),
        season: str = "winter",
    ) -> dict[str, Any]:
        name = f"classification_{season}_report.json"
        payload = _read_json(root / "processed" / "classification" / name)
        payload["_artefact"] = f"processed/classification/{name}"
        return payload

    @app.get("/analysis/classification/evidence")
    def classification_evidence(
        root: Path = Depends(root_dep),
        season: str = "winter",
    ) -> dict[str, Any]:
        name = f"classification_{season}_evidence.json"
        payload = _read_json(root / "processed" / "classification" / name)
        payload["_artefact"] = f"processed/classification/{name}"
        return payload

    return app


app = create_app()
