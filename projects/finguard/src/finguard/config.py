"""FinGuard configuration helpers.

Thin, explicit wrappers around the shared data-path utility so that every
FinGuard module resolves dataset locations identically and fails loudly
when the external data drive is unavailable.
"""

from __future__ import annotations

from pathlib import Path

from relia.config.paths import resolve_project_data_dir

#: Fixed pipeline layout under ``<PORTFOLIO_DATA_ROOT>/finguard/`` (see
#: ``docs/architecture/finguard.md``).
DATA_SUBDIRS: tuple[str, ...] = ("raw", "interim", "processed", "models")


def data_dir(*, create: bool = False) -> Path:
    """Return the validated FinGuard dataset directory on the external drive.

    Raises the ``relia.config.paths`` errors when ``PORTFOLIO_DATA_ROOT`` is
    unconfigured or unusable — never a silent fallback to the repo drive.
    """
    return resolve_project_data_dir("finguard", create=create)


def data_subdir(name: str, *, create: bool = False) -> Path:
    """Return one of the fixed pipeline subdirectories (``raw``, ...).

    Raises:
        ValueError: If *name* is not one of :data:`DATA_SUBDIRS`.
    """
    if name not in DATA_SUBDIRS:
        raise ValueError(
            f"Unknown data subdirectory {name!r}; expected one of {', '.join(DATA_SUBDIRS)}"
        )
    subdir = data_dir(create=create) / name
    if create:
        subdir.mkdir(parents=True, exist_ok=True)
    return subdir
