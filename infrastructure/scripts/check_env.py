"""Environment audit script (stdlib-only).

Prints the state of the development environment: Python, uv, git, docker,
disk space and the portfolio data root. Runs with any Python >= 3.9; safe
to execute outside the repository venv, e.g.:

    py -3.11 infrastructure/scripts/check_env.py
    uv run python infrastructure/scripts/check_env.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

_DATA_ROOT_ENV_VAR = "PORTFOLIO_DATA_ROOT"
_GIB = 1024**3


def _tool_version(command: list[str]) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not available"
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else "unknown"


def _disk_free(path: str) -> str:
    try:
        return f"{shutil.disk_usage(path).free / _GIB:.1f} GiB free"
    except OSError:
        return "unavailable"


def main() -> int:
    print(f"Platform:        {platform.platform()}")
    print(f"Python:          {platform.python_version()} at {sys.executable}")
    print(f"uv:              {_tool_version(['uv', '--version'])}")
    print(f"git:             {_tool_version(['git', '--version'])}")
    print(f"docker:          {_tool_version(['docker', '--version'])}")
    print(f"node:            {_tool_version(['node', '--version'])}")
    print()
    print(f"C: free space:   {_disk_free('C:\\\\')}")
    print(f"D: free space:   {_disk_free('D:\\\\')}")
    print()

    data_root = os.environ.get(_DATA_ROOT_ENV_VAR, "").strip()
    if not data_root:
        print(f"{_DATA_ROOT_ENV_VAR}: NOT SET in this process environment")
        print("  persistent value (setx) applies to NEW processes only;")
        print("  or rely on the repository .env via 'uv run relia check-data-root'.")
        return 1

    print(f"{_DATA_ROOT_ENV_VAR}: {data_root}")
    if not os.path.exists(data_root):
        print("  -> does not exist")
        return 1
    if not os.path.isdir(data_root):
        print("  -> not a directory")
        return 1
    print(f"  -> exists ({_disk_free(data_root)})")
    for project in ("terrascope", "finguard", "shared"):
        marker = "ok " if os.path.isdir(os.path.join(data_root, project)) else "MISSING"
        print(f"  - {project}: {marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
