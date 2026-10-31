"""RELIA command-line interface.

Currently exposes data-root diagnostics. Evaluation and regression
commands are planned; see ``docs/architecture/relia.md`` and the roadmap.
"""

from __future__ import annotations

import argparse
import sys

from relia.config.paths import DataRootError, DataRootStatus, check_data_root

_GIB = 1024**3


def _format_status(status: DataRootStatus) -> str:
    lines = [
        f"Data root:           {status.root}",
        f"Configured via:      {status.source}",
        f"Exists:              {status.exists}",
        f"Is a directory:      {status.is_dir}",
        f"Writable:            {status.writable}",
    ]
    if status.free_bytes is not None:
        lines.append(f"Free space:          {status.free_bytes / _GIB:.1f} GiB")
    lines.append(
        "Project directories: present="
        + (", ".join(status.present_projects) or "-")
        + " missing="
        + (", ".join(status.missing_projects) or "-")
    )
    lines.append(f"Healthy:             {status.healthy}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="relia",
        description="RELIA reliability infrastructure CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "check-data-root",
        help="Validate PORTFOLIO_DATA_ROOT and the dataset directory layout",
    )
    args = parser.parse_args(argv)

    if args.command == "check-data-root":
        try:
            status = check_data_root()
        except DataRootError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(_format_status(status))
        return 0 if status.healthy else 1

    parser.error(f"Unknown command {args.command!r}")
    return 2  # pragma: no cover - parser.error exits


if __name__ == "__main__":
    raise SystemExit(main())
