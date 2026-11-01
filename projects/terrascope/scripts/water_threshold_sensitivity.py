"""MNDWI threshold-sensitivity QA for the water-extent series (M0 close-out).

For every usable (non-abstained) scene date in the window, recomputes the
Ramsar-polygon water fraction across a threshold sweep and reports the spread.
The v0 threshold (0.0) is defensible only if the reported fractions are not
wildly threshold-dependent; the sweep quantifies exactly that.

Usage:
    uv run --project projects/terrascope python scripts/water_threshold_sensitivity.py \
        --start 2023-10-01 --end 2024-03-31 [--out <json path>]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

from terrascope.config import data_dir
from terrascope.features.indices import mndwi
from terrascope.features.water_extent import ramsar_mask_on_grid, scene_date
from terrascope.ingestion.aoi import approximate_pallikaranai_aoi
from terrascope.ingestion.cog_reader import CompositeGrid, read_band_onto_grid, read_scl_onto_grid
from terrascope.ingestion.gate import DownloadGate
from terrascope.ingestion.masking import scl_valid_mask
from terrascope.ingestion.pipeline import IngestionConfig, iter_cached_scenes

THRESHOLDS = (-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    root = data_dir()
    config = IngestionConfig()
    grid20 = (
        CompositeGrid.from_aoi(approximate_pallikaranai_aoi(), resolution_m=10.0)
        .at_resolution(2)
    )
    boundary = root / "raw" / "boundaries" / "ramsar_in2481.geojson"
    ramsar = ramsar_mask_on_grid(boundary, grid20)
    gate = DownloadGate()

    rows: list[dict] = []
    for _, scene_dir in iter_cached_scenes(root, start=args.start, end=args.end, config=config):
        scl = read_scl_onto_grid(str(scene_dir / "SCL.tif"), grid20, gate)
        valid = scl_valid_mask(scl, config.scl_exclude) & ramsar
        valid_px = int(np.count_nonzero(valid))
        if valid_px == 0:
            continue
        scene_valid = float(np.count_nonzero(scl_valid_mask(scl, config.scl_exclude)))
        scene_valid_fraction = scene_valid / scl.size
        if scene_valid_fraction < 0.80:
            continue  # abstained dates have no water claim to sensitivity-check
        green = read_band_onto_grid(str(scene_dir / "B03.tif"), "B03", grid20, gate)
        swir1 = read_band_onto_grid(str(scene_dir / "B11.tif"), "B11", grid20, gate)
        index = mndwi(green, swir1)
        index_values = index[valid]
        fractions = {
            f"{threshold:+.2f}": round(
                float(np.count_nonzero(index_values > threshold)) / valid_px, 4
            )
            for threshold in THRESHOLDS
        }
        rows.append(
            {
                "sensing_date": scene_date(scene_dir.name).isoformat(),
                "valid_fraction": round(scene_valid_fraction, 4),
                "valid_px_ramsar": valid_px,
                "mndwi_pctl_ramsar": {
                    "p10": round(float(np.nanpercentile(index_values, 10)), 3),
                    "p50": round(float(np.nanpercentile(index_values, 50)), 3),
                    "p90": round(float(np.nanpercentile(index_values, 90)), 3),
                },
                "water_fraction_ramsar": fractions,
            }
        )

    payload = {
        "method": "MNDWI threshold sweep within the Ramsar IN2481 polygon, usable dates only",
        "thresholds": THRESHOLDS,
        "rows": rows,
    }
    out_path = args.out or (
        root / "processed" / "water-extent" / f"threshold_sensitivity_{args.start}_{args.end}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    for row in rows:
        print(
            f"  {row['sensing_date']}: MNDWI p10/p50/p90 = "
            f"{row['mndwi_pctl_ramsar']['p10']:+.2f}/{row['mndwi_pctl_ramsar']['p50']:+.2f}/"
            f"{row['mndwi_pctl_ramsar']['p90']:+.2f} | "
            + " ".join(f"{k}:{v:.3f}" for k, v in row["water_fraction_ramsar"].items())
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
