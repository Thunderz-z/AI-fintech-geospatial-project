"""FinGuard package tests (foundation phase)."""

from pathlib import Path

from finguard import __version__
from finguard.config import data_dir
from relia.config.paths import get_data_root


def test_version_declared() -> None:
    assert __version__


def test_data_dir_resolves_under_data_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "data root"  # space on purpose: paths contain spaces
    (root / "finguard").mkdir(parents=True)
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))

    assert data_dir() == (root / "finguard").resolve()
    assert get_data_root() == root.resolve()


def test_unknown_project_rejected(tmp_path: Path, monkeypatch) -> None:
    from relia.config.paths import resolve_project_data_dir

    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(tmp_path))

    try:
        resolve_project_data_dir("../escaped")
    except ValueError as exc:
        assert "Unknown project" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown project")
