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
    report = run_composite(aoi, start=args.start, end=args.end, root=root_path)
    print(f"scenes used: {len(report.scenes_used)}")
    for season, count in report.season_scene_counts.items():
        max_obs = report.valid_obs_max[season]
        print(f"  {season}: {count} scene(s), max valid obs per pixel: {max_obs}")
    for path in report.composites:
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DownloadNotApprovedError as exc:
        print(f"BALKED: {exc}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
