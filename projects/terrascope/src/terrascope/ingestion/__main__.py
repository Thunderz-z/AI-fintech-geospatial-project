"""Ingestion CLI — the explicit approval gate is here.

Commands:

* ``status``    — offline summary: data root, AOI, bands, seasons, cache state.
* ``download``  — STAC search + AOI windowed reads into ``raw/``.
                  **Requires ``--approve``**: without it the command refuses to
                  touch the network and prints the exact command it would run.
* ``composite`` — build seasonal median composites from cached windows into
                  ``processed/`` (offline).

Usage::

    uv run --project projects/terrascope python -m terrascope.ingestion status
    uv run --project projects/terrascope python -m terrascope.ingestion download \\
        --start 2024-01-01 --end 2024-03-31 --approve
    uv run --project projects/terrascope python -m terrascope.ingestion composite \\
        --start 2024-01-01 --end 2024-03-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from terrascope.ingestion.aoi import approximate_pallikaranai_aoi
from terrascope.ingestion.gate import DownloadGate, DownloadNotApprovedError
from terrascope.ingestion.pipeline import IngestionConfig, run_composite, run_download

_DOWNLOAD_TEMPLATE = (
    "uv run --project projects/terrascope python -m terrascope.ingestion download "
    "--start {start} --end {end} --approve"
)


def _parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        msg = f"Invalid date {value!r} (expected YYYY-MM-DD)"
        raise argparse.ArgumentTypeError(msg) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m terrascope.ingestion",
        description="TerraScope Sentinel-2 ingestion (approval-gated).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="offline summary of AOI, config and cache")
    status.add_argument("--root", type=str, default=None, help="data-root override (testing)")

    for name, help_text in (
        ("download", "STAC search + AOI windowed reads into raw/ (needs --approve)"),
        ("composite", "seasonal median composites from cached windows"),
        ("water", "offline: water-extent series + evidence contract (no composites)"),
        ("analyse", "offline: composites + indices + water-extent series + evidence contract"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "--start", type=_parse_date, required=True, help="start date (YYYY-MM-DD, inclusive)"
        )
        cmd.add_argument(
            "--end", type=_parse_date, required=True, help="end date (YYYY-MM-DD, inclusive)"
        )
        cmd.add_argument("--root", type=str, default=None, help="data-root override (testing)")
        if name == "download":
            cmd.add_argument(
                "--approve",
                action="store_true",
                help="explicitly approve the network retrieval (required)",
            )
        if name in ("analyse", "water"):
            cmd.add_argument(
                "--boundary",
                type=str,
                default=None,
                help="authoritative boundary GeoJSON (default: Ramsar IN2481 on the data root)",
            )
        if name == "water":
            cmd.add_argument(
                "--calibration",
                type=str,
                default=None,
                help="calibration artefact JSON (round-2 T2); emits _v1 outputs",
            )
    return parser


def _print_status(root: str | None) -> int:
    from relia.config.paths import check_data_root

    aoi = approximate_pallikaranai_aoi()
    config = IngestionConfig()
    print("TerraScope ingestion status (offline)")
    print(f"  AOI: {aoi.name}")
    print(f"  bbox (EPSG:4326): {aoi.bbox_wgs84}")
    print(f"  boundary status: {aoi.boundary_status}")
    print(f"  bands 10 m: {' '.join(config.bands_10m)}")
    print(f"  bands 20 m: {' '.join(config.bands_20m)}")
    print(f"  SCL excluded classes: {sorted(config.scl_exclude)}")
    seasons = {name: sorted(months) for name, months in config.season_months.items()}
    print(f"  seasons: {json.dumps(seasons)}")
    try:
        status_snapshot = check_data_root()
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, don't crash
        print(f"  data root: UNAVAILABLE ({exc})")
        return 0
    print(f"  data root: {status_snapshot.root} (source: {status_snapshot.source})")
    print(f"  data root writable: {status_snapshot.writable}")
    if status_snapshot.free_bytes is not None:
        print(f"  free space: {status_snapshot.free_bytes / 1024**3:.1f} GB")
    if root:
        print(f"  (root override for this run: {root})")
    print("  downloads: BLOCKED unless the download command is run with --approve")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = getattr(args, "root", None)
    root_path = Path(root) if root else None

    if args.command == "status":
        return _print_status(root)

    aoi = approximate_pallikaranai_aoi()
    if args.command == "download":
        if not args.approve:
            print(
                "Download NOT approved: satellite retrieval requires explicit approval "
                "(AGENTS.md storage rules; M0 hard stop). To perform the retrieval:\n"
                f"  {_DOWNLOAD_TEMPLATE.format(start=args.start, end=args.end)}"
            )
            return 2
        gate = DownloadGate.approved()
        report = run_download(
            aoi,
            start=args.start,
            end=args.end,
            gate=gate,
            root=root_path,
        )
        cached = len(report.scenes_cached)
        print(f"scenes fetched: {len(report.scenes_read)}; already cached: {cached}")
        print(f"candidates filtered out: {report.scenes_filtered_out}")
        print(f"files written: {len(report.files_written)}; total: {report.total_mb:.1f} MB")
        for scene, fraction in report.valid_fractions.items():
            print(f"  SCL valid fraction {scene}: {fraction:.2%}")
        return 0

    # composite
    if args.command == "composite":
        report = run_composite(aoi, start=args.start, end=args.end, root=root_path)
        print(f"scenes used: {len(report.scenes_used)}")
        for season, count in report.season_scene_counts.items():
            max_obs = report.valid_obs_max[season]
            print(f"  {season}: {count} scene(s), max valid obs per pixel: {max_obs}")
        for path in report.composites:
            print(f"  wrote {path}")
        return 0

    # water
    if args.command == "water":
        return _run_water(args, root_path)

    # analyse
    return _run_analyse(args, root_path)


def _run_water(args: argparse.Namespace, root_path: Path | None) -> int:
    """Offline water-extent series + evidence contract (no composites needed)."""
    from terrascope.config import data_dir
    from terrascope.evidence.water import water_extent_contract, write_contract
    from terrascope.features.water_extent import (
        DEFAULT_MNDWI_WATER_THRESHOLD,
        water_extent_time_series,
        write_water_extent_report,
    )

    root = root_path if root_path is not None else data_dir()
    boundary = (
        Path(args.boundary)
        if args.boundary
        else root / "raw" / "boundaries" / "ramsar_in2481.geojson"
    )
    if not boundary.is_file():
        print(f"boundary file missing: {boundary}")
        return 1

    calibration = None
    calibration_path = getattr(args, "calibration", None)
    if calibration_path:
        calibration_file = Path(calibration_path)
        if not calibration_file.is_file():
            print(f"calibration artefact missing: {calibration_file}")
            return 1
        calibration = json.loads(calibration_file.read_text(encoding="utf-8"))

    threshold = float(calibration["threshold"]) if calibration else DEFAULT_MNDWI_WATER_THRESHOLD
    version = "_v1" if calibration else ""
    observations = water_extent_time_series(
        start=args.start,
        end=args.end,
        boundary_geojson=boundary,
        root=root,
        threshold=threshold,
    )
    out_dir = root / "processed" / "water-extent"
    report_path = write_water_extent_report(
        observations, out_dir / f"water_extent_{args.start}_{args.end}{version}.json"
    )
    print(f"  water-extent report: {report_path}")
    for obs in observations:
        if obs.abstained:
            print(f"  {obs.sensing_date}: ABSTAINED ({obs.valid_fraction:.0%} valid)")
        else:
            aoi_pct = obs.water_fraction_aoi * 100
            ramsar_pct = (obs.water_fraction_ramsar or 0) * 100
            print(
                f"  {obs.sensing_date}: water {aoi_pct:5.1f}% of AOI | "
                f"{ramsar_pct:5.1f}% of Ramsar | {obs.valid_fraction:.0%} valid"
            )

    contract = water_extent_contract(
        observations,
        start=args.start,
        end=args.end,
        report_path=report_path,
        threshold=threshold,
        min_valid_fraction=0.80,
        calibration=calibration,
    )
    contract_path = write_contract(
        contract, out_dir / f"water_extent_{args.start}_{args.end}{version}.evidence.json"
    )
    print(f"  evidence contract: {contract_path} ({contract.validation_status.value})")
    print(f"  claim: {contract.claim_text}")
    return 0


def _run_analyse(args: argparse.Namespace, root_path: Path | None) -> int:
    """Offline full analysis: composites -> indices -> water series -> contract."""
    from terrascope.config import data_dir
    from terrascope.features.indices import build_season_indices

    aoi = approximate_pallikaranai_aoi()
    root = root_path if root_path is not None else data_dir()
    composite_report = run_composite(aoi, start=args.start, end=args.end, root=root)

    season_dirs = sorted({path.parent for path in composite_report.provenance})
    for season_dir in season_dirs:
        index_paths = build_season_indices(season_dir)
        names = ", ".join(sorted(path.name for path in index_paths.values()))
        print(f"  indices[{season_dir.name}]: {names}")

    return _run_water(args, root_path)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DownloadNotApprovedError as exc:
        print(f"BALKED: {exc}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
