"""Configuration utilities: data-root resolution and validation."""

from relia.config.paths import (
    DataRootError,
    DataRootNotConfiguredError,
    DataRootUnavailableError,
    check_data_root,
    get_data_root,
    resolve_project_data_dir,
)

__all__ = [
    "DataRootError",
    "DataRootNotConfiguredError",
    "DataRootUnavailableError",
    "check_data_root",
    "get_data_root",
    "resolve_project_data_dir",
]
