"""Render QA quicklooks for TerraScope composites (visual QA, roadmap M0 step 4).

Usage:
    uv run --project projects/terrascope python scripts/render_quicklooks.py \
        <season_composite_dir> <boundary_geojson> <out_png_prefix>

Reads the seasonal composites written by ``terrascope.ingestion.pipeline.run_composite``
(RGB at 10 m, NDVI/NDWI from 10 m bands) and overlays the authoritative Ramsar
boundary. Display-only resampling (2x repeat for any 20 m grid use) — analysis
code must use the grid-aligned readers instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from terrascope.ingestion.cog_reader import CompositeGrid  # noqa: E402


def _stretch(band: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray:
    valid = band[np.isfinite(band) & (band > 0)]
    lo, hi = np.percentile(valid, [low_pct, high_pct])
    stretched = (band.astype(np.float32) - lo) / max(hi - lo, 1e-6)
    return np.clip(stretched, 0.0, 1.0)


def _read_median(season_dir: Path, band: str) -> np.ndarray:
    with rasterio.open(season_dir / f"{band}_median.tif") as src:
        array = src.read(1).astype(np.float32)
        array[array == 0] = np.nan  # 0 is the composite nodata value
        return array


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 1
    season_dir, boundary_path, out_prefix = (Path(a) for a in argv[1:])
    provenance = json.loads((season_dir / "provenance.json").read_text(encoding="utf-8"))
    grid_info = provenance["grid"]
    grid = CompositeGrid(
        crs_epsg=int(grid_info["crs"].split(":")[1]),
        transform=__import__("affine").Affine(*grid_info["transform"][:6]),
        width=grid_info["width"],
        height=grid_info["height"],
        resolution_m=grid_info["resolution_m"],
    )

    red = _read_median(season_dir, "B04")
    green = _read_median(season_dir, "B03")
    blue = _read_median(season_dir, "B02")
    nir = _read_median(season_dir, "B08")

    extent = (grid.bounds[0], grid.bounds[2], grid.bounds[1], grid.bounds[3])  # l, r, b, t

    def _plot(ax: plt.Axes, data: np.ndarray, title: str, cmap: str | None = None) -> None:
        if cmap is None:
            ax.imshow(data, extent=extent, origin="upper")
        else:
            ax.imshow(data, extent=extent, origin="upper", cmap=cmap, vmin=-0.5, vmax=0.8)
        # Overlay the authoritative Ramsar boundary reprojected to the grid CRS.
        import geopandas as gpd

        boundary = gpd.read_file(boundary_path).to_crs(grid.crs_epsg)
        boundary.boundary.plot(ax=ax, color="red", linewidth=1.2)
        ax.set_title(title)
        ax.set_xlabel("E (m, EPSG:32644)")
        ax.set_ylabel("N (m)")

    rgb = np.dstack([_stretch(red), _stretch(green), _stretch(blue)])
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (nir - red) / (nir + red)
        ndwi = (green - nir) / (green + nir)

    figure, axes = plt.subplots(1, 3, figsize=(21, 7), dpi=110)
    scene_count = len(provenance["scene_ids"])
    _plot(axes[0], rgb, f"{provenance['season']} composite — RGB quicklook ({scene_count} scenes)")
    _plot(axes[1], ndvi, "NDVI (median composite)", cmap="RdYlGn")
    _plot(axes[2], ndwi, "NDWI (median composite) — water > 0", cmap="BrBG")
    figure.suptitle(
        f"TerraScope QA — {provenance['season']} {provenance['start']}..{provenance['end']} | "
        f"grid {grid.width}x{grid.height} @ {grid.resolution_m:.0f} m | red line: Ramsar IN2481"
    )
    figure.tight_layout()
    out_path = out_prefix.with_suffix(".png")
    figure.savefig(out_path, bbox_inches="tight")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
