"""Per-scene water-extent time series v0 (MNDWI threshold on SCL-masked L2A).

Method (v0, deliberately simple and fully documented):

1. Re-project each cached scene's B03 (green, 10 m), B11 (SWIR1, 20 m) and SCL
   onto the fixed 20 m composite grid (the same grid the download clipped to).
2. Mask with SCL (exclude nodata/saturated/cloud/cirrus/snow classes).
3. MNDWI = (B03 - B11) / (B03 + B11); water = MNDWI > threshold (default 0).
4. Water fraction = water pixels / valid pixels — over the approximate study
   AOI grid and, separately, within the authoritative Ramsar IN2481 polygon.
5. Scenes with SCL valid fraction below ``min_valid_fraction`` are recorded as
   **abstained**: no water-fraction claim for that date.

Honesty notes: the threshold is uncalibrated (turbid marsh water straddles
MNDWI ~ 0); the AOI fractions use the approximate bbox boundary — only the
Ramsar-polygon fractions carry an authoritative boundary. Nothing here asserts
causation; this is an observation series.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from rasterio.features import rasterize

from terrascope.config import data_dir
from terrascope.features.indices import mndwi
from terrascope.ingestion.aoi import approximate_pallikaranai_aoi
from terrascope.ingestion.cog_reader import CompositeGrid, read_band_onto_grid, read_scl_onto_grid
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.masking import SCL_EXCLUDE_DEFAULT, scl_valid_mask
from terrascope.ingestion.pipeline import (
    IngestionConfig,
    iter_cached_scenes,
    scene_date_from_id,
    scene_processing_stamp,
)

__all__ = [
    "DEFAULT_MNDWI_WATER_THRESHOLD",
    "WaterExtentObservation",
    "ramsar_mask_on_grid",
    "scene_water_extent",
    "water_extent_time_series",
    "write_water_extent_report",
]

#: v0 water threshold (uncalibrated; revisit with the first QA histograms).
DEFAULT_MNDWI_WATER_THRESHOLD = 0.0


@dataclass(frozen=True)
class WaterExtentObservation:
    """One date's water-extent observation (or its explicit abstention)."""

    scene_id: str
    sensing_date: str
    processing_stamp: str
    valid_fraction: float
    water_fraction_aoi: float | None
    water_fraction_ramsar: float | None
    valid_px_aoi: int
    water_px_aoi: int
    valid_px_ramsar: int
    water_px_ramsar: int
    threshold: float
    abstained: bool
    abstention_reason: str | None


def ramsar_mask_on_grid(boundary_geojson: Path, grid: CompositeGrid) -> np.ndarray:
    """Rasterize the authoritative boundary polygon onto *grid* (True = inside)."""
    boundary = gpd.read_file(boundary_geojson).to_crs(grid.crs_epsg)
    burned = rasterize(
        ((geometry, 1) for geometry in boundary.geometry),
        out_shape=grid.shape,
        transform=grid.transform,
        fill=0,
        dtype="uint8",
    )
    return burned.astype(bool)


def scene_water_extent(
    scene_dir: Path,
    grid20: CompositeGrid,
    ramsar_mask: np.ndarray,
    *,
    scl_exclude: frozenset[int] | set[int] = SCL_EXCLUDE_DEFAULT,
    threshold: float = DEFAULT_MNDWI_WATER_THRESHOLD,
    min_valid_fraction: float = 0.80,
    gate: DownloadGate | None = None,
) -> WaterExtentObservation:
    """Compute one scene's water extent (or record why it is abstained)."""
    gate = gate or DownloadGate()  # local cache reads only
    scene_id = scene_dir.name
    scl = read_scl_onto_grid(str(scene_dir / "SCL.tif"), grid20, gate)
    valid = scl_valid_mask(scl, scl_exclude)
    green = read_band_onto_grid(str(scene_dir / "B03.tif"), "B03", grid20, gate)
    swir1 = read_band_onto_grid(str(scene_dir / "B11.tif"), "B11", grid20, gate)
    water_index = mndwi(green, swir1)

    valid_px = int(np.count_nonzero(valid))
    scene_valid_fraction = valid.mean() if valid.size else 0.0
    water = (water_index > threshold) & valid

    ramsar_valid = valid & ramsar_mask
    ramsar_water = water & ramsar_mask

    abstained = bool(scene_valid_fraction < min_valid_fraction or valid_px == 0)
    reason = None
    if abstained:
        reason = (
            f"SCL valid fraction {scene_valid_fraction:.2f} below the "
            f"{min_valid_fraction:.2f} gating threshold (cloud/quality masking)."
        )

    def _fraction(water_pixels: int, valid_pixels: int) -> float | None:
        if abstained or valid_pixels == 0:
            return None
        return water_pixels / valid_pixels

    return WaterExtentObservation(
        scene_id=scene_id,
        sensing_date=scene_date(scene_id).isoformat(),
        processing_stamp=scene_processing_stamp(scene_id),
        valid_fraction=round(float(scene_valid_fraction), 4),
        water_fraction_aoi=_fraction(int(np.count_nonzero(water)), valid_px),
        water_fraction_ramsar=_fraction(
            int(np.count_nonzero(ramsar_water)), int(np.count_nonzero(ramsar_valid))
        ),
        valid_px_aoi=valid_px,
        water_px_aoi=int(np.count_nonzero(water)),
        valid_px_ramsar=int(np.count_nonzero(ramsar_valid)),
        water_px_ramsar=int(np.count_nonzero(ramsar_water)),
        threshold=threshold,
        abstained=abstained,
        abstention_reason=reason,
    )


def scene_date(scene_id: str) -> dt.date:
    """Sensing date of a scene ID (raises when unparseable)."""
    date = scene_date_from_id(scene_id)
    if date is None:
        msg = f"Cannot parse sensing date from scene id {scene_id!r}"
        raise ValueError(msg)
    return date


def water_extent_time_series(
    *,
    start: dt.date,
    end: dt.date,
    boundary_geojson: Path,
    config: IngestionConfig | None = None,
    root: Path | None = None,
    threshold: float = DEFAULT_MNDWI_WATER_THRESHOLD,
    min_valid_fraction: float = 0.80,
) -> list[WaterExtentObservation]:
    """Water-extent observations for every cached scene date in the window.

    Scenes are deduplicated per sensing datetime (latest processing baseline
    wins — see ``terrascope.ingestion.pipeline.iter_cached_scenes``).
    """
    config = config or IngestionConfig()
    root = root or data_dir()
    grid10 = CompositeGrid.from_aoi(
        approximate_pallikaranai_aoi(),
        resolution_m=config.grid_resolution_m,
        epsg=config.grid_crs_epsg,
    )
    grid20 = grid10.at_resolution(2)
    ramsar_mask = ramsar_mask_on_grid(boundary_geojson, grid20)
    gate = DownloadGate()  # local cache reads only; never trips the gate

    observations: list[WaterExtentObservation] = []
    for _, scene_dir in iter_cached_scenes(root, start=start, end=end, config=config):
        observations.append(
            scene_water_extent(
                scene_dir,
                grid20,
                ramsar_mask,
                scl_exclude=config.scl_exclude,
                threshold=threshold,
                min_valid_fraction=min_valid_fraction,
                gate=gate,
            )
        )
    return observations


def write_water_extent_report(
    observations: list[WaterExtentObservation], out_path: Path
) -> Path:
    """Persist the observation series as JSON (data only — claims live in
    evidence contracts)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "method": "MNDWI > threshold on SCL-masked Sentinel-2 L2A, per sensing date, "
        "deduplicated to the latest processing baseline",
        "aoi": "approximate study bbox grid (EPSG:32644, 20 m); Ramsar IN2481 polygon separately",
        "observations": [asdict(observation) for observation in observations],
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
