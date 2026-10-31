"""TerraScope package tests (foundation phase)."""

from pathlib import Path

from relia.config.paths import get_data_root
from terrascope import __version__
from terrascope.config import data_dir


def test_version_declared() -> None:
    assert __version__


def test_data_dir_resolves_under_data_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data root"  # space on purpose: paths contain spaces
    (root / "terrascope").mkdir(parents=True)
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))

    assert data_dir() == (root / "terrascope").resolve()
    assert get_data_root() == root.resolve()


def test_data_dir_missing_subtree_raises(tmp_path: Path, monkeypatch) -> None:
    from relia.config.paths import DataRootUnavailableError

    root = tmp_path / "data root"
    root.mkdir(parents=True)  # no terrascope/ subtree
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))

    try:
        data_dir()
    except DataRootUnavailableError as exc:
        assert "terrascope" in str(exc)
    else:
        raise AssertionError("expected DataRootUnavailableError")
