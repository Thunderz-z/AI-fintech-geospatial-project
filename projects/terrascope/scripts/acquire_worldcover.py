"""Acquire the ESA WorldCover 2021 v200 AOI subset (round-2 T1, owner-approved).

Windowed COG read of the ``map`` asset, clipped to the approximate-AOI
composite-grid bounds (the same extent the Sentinel-2 windows cover), saved
as-acquired under ``raw/esa-worldcover/`` with a SHA-256 acquisition-log entry.
Run only after owner approval (round-2 plan §2 T1):

    uv run --project projects/terrascope python scripts/acquire_worldcover.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import planetary_computer
import pystac_client
import rasterio

from terrascope.config import data_dir
from terrascope.ingestion.aoi import approximate_pallikaranai_aoi
from terrascope.ingestion.cog_reader import CompositeGrid, window_covering_bounds
from terrascope.ingestion.gate import DownloadGate

COLLECTION = "esa-worldcover"
ITEM_PREFIX = "ESA_WorldCover_10m_2021_v200_"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    gate = DownloadGate.approved()  # this script IS the approved retrieval
    aoi = approximate_pallikaranai_aoi()
    grid10 = CompositeGrid.from_aoi(aoi, resolution_m=10.0)

    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=[COLLECTION], bbox=list(aoi.bbox_wgs84)
    )
    items = [item for item in search.items() if item.id.startswith(ITEM_PREFIX)]
    if len(items) != 1:
        msg = f"Expected exactly one {ITEM_PREFIX}* item for the AOI, got {[i.id for i in items]}"
        raise RuntimeError(msg)
    item = items[0]
    map_asset = item.assets["map"]
    href = map_asset.href
    gate.require(href, "WorldCover map asset windowed read")

    root = data_dir()
    out_dir = root / "raw" / "esa-worldcover"
    out_path = out_dir / f"{item.id}_AOI.tif"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(href) as dataset:
        window = window_covering_bounds(dataset, grid10.bounds, grid10.crs_epsg)
        array = dataset.read(1, window=window)
        transform = rasterio.windows.transform(window, dataset.transform)
        crs = dataset.crs
        nodata = dataset.nodata
        profile_info = {"driver": "GTiff", "width": dataset.width, "height": dataset.height}

    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=str(array.dtype),
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
        tiled=True,
    ) as dst:
        dst.write(array, 1)

    size = out_path.stat().st_size
    log_path = root / "raw" / "esa-worldcover" / "acquisition_log.jsonl"
    entry = {
        "acquired_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "product": "ESA WorldCover 2021 v200 (10 m land cover, CC BY 4.0)",
        "item": item.id,
        "asset": "map",
        "file": str(out_path.relative_to(root)),
        "bytes": size,
        "sha256": _sha256(out_path),
        "window_crs": str(crs),
        "window_shape": list(array.shape),
        "class_histogram": {
            str(int(value)): int(count)
            for value, count in zip(*np.unique(array, return_counts=True), strict=True)
        },
        "source_collection": f"{COLLECTION} (Microsoft Planetary Computer)",
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")

    print(f"item: {item.id}")
    print(
        f"window: {array.shape} px, crs {crs} "
        f"(source raster {profile_info['width']}x{profile_info['height']})"
    )
    print(f"wrote {out_path} ({size} bytes)")
    print(f"sha256: {entry['sha256']}")
    print(f"class histogram: {entry['class_histogram']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
