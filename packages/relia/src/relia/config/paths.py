"""Portfolio data-path configuration.

All substantial datasets for this portfolio live on an external drive, never
inside the Git repository. The single source of truth for that location is the
``PORTFOLIO_DATA_ROOT`` environment variable, optionally provided through the
repository's local ``.env`` file (which is never committed).

Design rules (see ``docs/decisions/0003-external-data-root.md``):

* No silent fallback to the internal drive for datasets.
* Clear, typed errors when the data root is not configured, does not exist,
  or is not writable.
* Paths containing spaces (the deployed root does) are handled through
  ``pathlib`` end-to-end; no shell string concatenation happens here.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import disk_usage

__all__ = [
    "DATA_ROOT_ENV_VAR",
    "KNOWN_PROJECTS",
    "DataRootError",
    "DataRootNotConfiguredError",
    "DataRootStatus",
    "DataRootUnavailableError",
    "check_data_root",
    "find_repo_root",
    "get_data_root",
    "read_dotenv",
    "resolve_project_data_dir",
]

DATA_ROOT_ENV_VAR = "PORTFOLIO_DATA_ROOT"

_REPO_MARKERS = (".python-version", "pyproject.toml")

#: Projects with a reserved subtree below the data root (see ADR-0003).
KNOWN_PROJECTS: tuple[str, ...] = ("terrascope", "finguard", "shared")


class DataRootError(RuntimeError):
    """Base class for data-root configuration problems."""


class DataRootNotConfiguredError(DataRootError):
    """Raised when no data root is configured via environment or .env."""


class DataRootUnavailableError(DataRootError):
    """Raised when the configured data root exists but cannot be used."""


def _read_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal ``.env`` file: KEY=VALUE lines, '#' comments, optional quotes."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def read_dotenv(path: Path) -> dict[str, str]:
    """Public access to the minimal ``.env`` parser.

    Added additively so other RELIA configuration surfaces (e.g. provider
    credentials via ``RELIA_LLM_*``) can fall back to the repository's local
    ``.env`` without duplicating the parsing rules. Behaviour is identical to
    the internal parser used for the data root.
    """
    return _read_dotenv(path)


def _configured_value(start: Path | None) -> tuple[str, str]:
    """Return the configured raw value and its source ("environment" or ".env")."""
    value = os.environ.get(DATA_ROOT_ENV_VAR, "").strip()
    if value:
        return value, "environment"
    repo_root = find_repo_root(start)
    if repo_root is not None:
        dotenv = repo_root / ".env"
        if dotenv.is_file():
            value = _read_dotenv(dotenv).get(DATA_ROOT_ENV_VAR, "").strip()
            if value:
                return value, ".env"
    return "", "none"


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) to locate the repository root.

    The repository root is identified by containing both ``.python-version``
    and ``pyproject.toml``. Returns ``None`` when no such directory is found.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if all((candidate / marker).is_file() for marker in _REPO_MARKERS):
            return candidate
    return None


def _probe_writable(directory: Path) -> None:
    """Raise ``OSError`` if a temporary file cannot be created in *directory*."""
    handle, probe_path = tempfile.mkstemp(prefix=".relia-write-probe-", dir=directory)
    try:
        os.close(handle)
    finally:
        os.unlink(probe_path)


def get_data_root(start: Path | None = None) -> Path:
    """Return the validated portfolio data root.

    Resolution order:

    1. The ``PORTFOLIO_DATA_ROOT`` environment variable.
    2. The repository's local ``.env`` file (never committed), found by
       walking up from the working directory.

    Raises:
        DataRootNotConfiguredError: If neither source provides a value.
        DataRootUnavailableError: If the configured path does not exist,
            is not a directory, or is not writable.
    """
    configured, _ = _configured_value(start)
    if not configured:
        raise DataRootNotConfiguredError(
            f"{DATA_ROOT_ENV_VAR} is not set and no repository .env provides it. "
            "Set it to the external dataset root, e.g. "
            f'setx {DATA_ROOT_ENV_VAR} "D:\\GITHUB\\AI-Portfolio\\Portfolio data"'
        )

    root = Path(configured).expanduser()
    if not root.exists():
        raise DataRootUnavailableError(
            f"Configured data root does not exist: {root}. "
            "Connect the external dataset drive or fix "
            f"{DATA_ROOT_ENV_VAR}."
        )
    if not root.is_dir():
        raise DataRootUnavailableError(
            f"Configured data root is not a directory: {root}"
        )

    # Verify writability with a real probe; os.access() is unreliable on Windows.
    try:
        _probe_writable(root)
    except OSError as exc:
        raise DataRootUnavailableError(
            f"Configured data root is not writable: {root} ({exc})"
        ) from exc
    return root.resolve()


def resolve_project_data_dir(
    project: str, *, create: bool = False, start: Path | None = None
) -> Path:
    """Return the data directory for *project* below the data root.

    Args:
        project: One of ``KNOWN_PROJECTS`` ("terrascope", "finguard", "shared").
        create: Create the subtree when missing instead of raising.
        start: Optional start directory for repository/.env discovery.

    Raises:
        ValueError: If *project* is unknown (guards against path traversal).
        DataRootNotConfiguredError: If no data root is configured.
        DataRootUnavailableError: If the data root or project subtree is
            unusable, or missing while *create* is False.
    """
    if project not in KNOWN_PROJECTS:
        raise ValueError(
            f"Unknown project {project!r}; expected one of {', '.join(KNOWN_PROJECTS)}"
        )
    root = get_data_root(start=start)
    project_dir = root / project
    if project_dir.is_dir():
        return project_dir
    if create:
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir
    raise DataRootUnavailableError(
        f"Project data directory does not exist: {project_dir}. "
        "Create it or pass create=True."
    )


@dataclass(frozen=True)
class DataRootStatus:
    """Snapshot of data-root health, used by the CLI and environment checks."""

    root: Path
    source: str  # "environment" or ".env"
    exists: bool
    is_dir: bool
    writable: bool
    free_bytes: int | None
    present_projects: tuple[str, ...]
    missing_projects: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return (
            self.exists
            and self.is_dir
            and self.writable
            and not self.missing_projects
        )


def check_data_root(start: Path | None = None) -> DataRootStatus:
    """Collect a diagnostic snapshot of the data root.

    Raises:
        DataRootNotConfiguredError: If nothing is configured to inspect.
    """
    configured, source = _configured_value(start)
    if not configured:
        raise DataRootNotConfiguredError(
            f"{DATA_ROOT_ENV_VAR} is not set; cannot inspect the data root."
        )
    root = Path(configured).expanduser()
    exists = root.exists()
    is_dir = root.is_dir()
    writable = False
    if is_dir:
        try:
            _probe_writable(root)
            writable = True
        except OSError:
            writable = False
    free_bytes: int | None = None
    if exists:
        try:
            free_bytes = disk_usage(root).free
        except OSError:
            free_bytes = None
    present = tuple(p for p in KNOWN_PROJECTS if (root / p).is_dir())
    missing = tuple(p for p in KNOWN_PROJECTS if p not in present)
    return DataRootStatus(
        root=root,
        source=source,
        exists=exists,
        is_dir=is_dir,
        writable=writable,
        free_bytes=free_bytes,
        present_projects=present,
        missing_projects=missing,
    )
