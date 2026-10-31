"""TerraScope configuration helpers.

Thin, explicit wrappers around the shared data-path utility so that every
TerraScope module resolves dataset locations identically and fails loudly
when the external data drive is unavailable.
"""

from __future__ import annotations

from pathlib import Path

from relia.config.paths import resolve_project_data_dir


def data_dir(*, create: bool = False) -> Path:
    """Return the validated TerraScope dataset directory on the external drive.

    Raises the ``relia.config.paths`` errors when ``PORTFOLIO_DATA_ROOT`` is
    unconfigured or unusable — never a silent fallback to the repo drive.
    """
    return resolve_project_data_dir("terrascope", create=create)
