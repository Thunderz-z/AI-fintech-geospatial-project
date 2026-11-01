"""MNDWI threshold calibration (round-2 T2).

Calibrates the water threshold against the ESA WorldCover 2021 v200 permanent
water class (80) on the authoritative Ramsar polygon, over every usable cached
scene date, and scores the chosen threshold against manual QA points (visual
interpretation of the winter composite). Emits the calibration artefact JSON.

    uv run --project projects/terrascope python scripts/calibrate_water_threshold.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import rasterio

from terrascope.config import data_dir
from terrascope.features.calibration import (
    calibrate_threshold,
    read_reference_water_mask,
    result_to_dict,
    score_qa_points,
)
from terrascope.features.indices import mndwi
from terrascope.features.water_extent import ramsar_mask_on_grid
from terrascope.ingestion.aoi import approximate_pallikaranai_aoi
from terrascope.ingestion.cog_reader import CompositeGrid, read_scl_onto_grid
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.masking import scl_valid_mask
from terrascope.ingestion.pipeline import IngestionConfig, iter_cached_scenes

MIN_VALID_FRACTION = 0.80


def _usable_scene_dirs(
    root: Path, config: IngestionConfig, grid20: CompositeGrid, gate: DownloadGate
) -> list[Path]:
    usable: list[Path] = []
    for _, scene_dir in iter_cached_scenes(
        root,
        start=dt.date(2019, 4, 1),
        end=dt.date(2026, 10, 31),
        config=config,
    ):
        scl = read_scl_onto_grid(str(scene_dir / "SCL.tif"), grid20, gate)
        valid_fraction = float(np.count_nonzero(scl_valid_mask(scl, config.scl_exclude)))
        if valid_fraction / scl.size >= MIN_VALID_FRACTION:
            usable.append(scene_dir)
    return usable


def main() -> int:
    root = data_dir()
    config = IngestionConfig()
    grid10 = CompositeGrid.from_aoi(approximate_pallikaranai_aoi(), resolution_m=10.0)
    grid20 = grid10.at_resolution(2)
    gate = DownloadGate()  # local reads only

    wc_path = root / "raw" / "esa-worldcover" / "ESA_WorldCover_10m_2021_v200_N12E078_AOI.tif"
    boundary = root / "raw" / "boundaries" / "ramsar_in2481.geojson"
    qa_points = root / "raw" / "boundaries" / "manual_qa_points_2026-11.geojson"

    reference, reference_defined = read_reference_water_mask(
        wc_path, grid20, water_class_codes=(80,)
    )
    ramsar = ramsar_mask_on_grid(boundary, grid20)
    print(
        f"reference: {int(np.count_nonzero(reference & ramsar))} reference-water cells "
        f"of {int(np.count_nonzero(ramsar))} Ramsar cells"
    )

    usable = _usable_scene_dirs(root, config, grid20, gate)
    print(f"usable dates (valid fraction >= {MIN_VALID_FRACTION:.0%}): {len(usable)}")

    result = calibrate_threshold(
        usable,
        grid20,
        reference,
        reference_defined,
        region_mask=ramsar,
        gate=gate,
    )
    print(f"chosen threshold: {result.threshold:+.2f}")
    print(f"mean kappa by threshold: {result.mean_kappa_by_threshold}")

    # Manual QA points against the WINTER composite MNDWI (the imagery the
    # points were interpreted from) — an independent check, not a fit target.
    winter_dir = root / "processed" / "composites" / "winter"
    with rasterio.open(winter_dir / "B03_median.tif") as src:
        green10 = src.read(1).astype(np.float32)
        green10[green10 == 0] = np.nan
    with rasterio.open(winter_dir / "B11_median.tif") as src:
        swir1 = src.read(1).astype(np.float32)
        swir1[swir1 == 0] = np.nan
    # B03 is on the 10 m grid; align to the 20 m grid by 2x2 block mean.
    h2, w2 = grid20.shape
    green20 = (
        np.nanmean(green10[: h2 * 2, : w2 * 2].reshape(h2, 2, w2, 2), axis=(1, 3))
        if green10.shape[0] >= h2 * 2
        else np.full(grid20.shape, np.nan, dtype=np.float32)
    )
    winter_mndwi = mndwi(green20, swir1)
    qa_scores = score_qa_points(qa_points, winter_mndwi, grid20, result.threshold)
    n_agree = sum(1 for s in qa_scores if s.agrees)
    print(
        f"QA points: {n_agree}/{len(qa_scores)} agree with the calibrated threshold "
        f"(winter composite MNDWI)"
    )
    for s in qa_scores:
        flag = "OK " if s.agrees else "MISS"
        print(f"  [{flag}] {s.name}: mndwi={s.mndwi:+.3f} expected_water={s.expected_water}")

    payload = {
        "calibration_date": dt.datetime.now(tz=dt.UTC).isoformat(),
        "reference_product": "ESA WorldCover 2021 v200, class 80 (permanent water), "
        "10 m -> 20 m fraction >= 0.5, windowed AOI (sha256 45032a61...)",
        "region": "Ramsar IN2481 polygon (authoritative boundary)",
        "qa_points_file": str(qa_points.name),
        "qa_points_method": "visual interpretation of the winter-2024 RGB quicklook",
        "min_valid_fraction": MIN_VALID_FRACTION,
        "n_usable_dates": result.n_dates,
        **result_to_dict(result),
        "qa_point_scores": [
            {
                "name": s.name,
                "expected_water": s.expected_water,
                "mndwi": None if not np.isfinite(s.mndwi) else s.mndwi,
                "predicted_water": s.predicted_water,
                "agrees": s.agrees,
            }
            for s in qa_scores
        ],
        "limitations": [
            "WorldCover is a 2021 single-epoch product compared against scenes from other years.",
            "'Permanent water' is not 'MNDWI-positive at acquisition time' (seasonal marsh water).",
            "Manual QA points are hand-interpreted from RGB, not surveyed ground truth.",
        ],
    }
    out_path = root / "processed" / "water-extent" / "mndwi_calibration_v1.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
