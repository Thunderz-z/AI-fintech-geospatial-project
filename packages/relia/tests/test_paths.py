"""Tests for the portfolio data-path utility (relia.config.paths)."""

import sys
from pathlib import Path

import pytest

from relia.config.paths import (
    DATA_ROOT_ENV_VAR,
    DataRootNotConfiguredError,
    DataRootUnavailableError,
    check_data_root,
    find_repo_root,
    get_data_root,
    resolve_project_data_dir,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from the developer machine's real configuration."""
    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)


def _make_root(base: Path, *projects: str) -> Path:
    root = base / "data root"  # space on purpose: the real root has one
    for project in ("terrascope", "finguard", "shared") if not projects else projects:
        (root / project).mkdir(parents=True, exist_ok=True)
    return root


def test_env_var_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_root(tmp_path)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))
    assert get_data_root() == root.resolve()


def test_missing_configuration_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no repo markers, no .env
    with pytest.raises(DataRootNotConfiguredError):
        get_data_root()


def test_dotenv_fallback_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".python-version").write_text("3.13\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repo / ".env").write_text(
        f'{DATA_ROOT_ENV_VAR}="D:\\\\fake\\\\root with space"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    # Resolution walks up from cwd and reads .env; the fake root doesn't
    # exist, which must surface as "unavailable", not "not configured".
    with pytest.raises(DataRootUnavailableError):
        get_data_root()


def test_env_var_beats_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".python-version").write_text("3.13\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (repo / ".env").write_text(f"{DATA_ROOT_ENV_VAR}=D:\\\\elsewhere\n", encoding="utf-8")
    root = _make_root(tmp_path / "outer")
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))
    monkeypatch.chdir(repo)

    assert get_data_root() == root.resolve()


def test_nonexistent_root_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path / "does-not-exist"))
    with pytest.raises(DataRootUnavailableError, match="does not exist"):
        get_data_root()


def test_file_as_root_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_root = tmp_path / "a-file"
    file_root.write_text("x", encoding="utf-8")
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(file_root))
    with pytest.raises(DataRootUnavailableError, match="not a directory"):
        get_data_root()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits are not enforced on Windows",
)
def test_unwritable_root_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:

    root = _make_root(tmp_path)
    root.chmod(0o555)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))
    try:
        with pytest.raises(DataRootUnavailableError, match="not writable"):
            get_data_root()
    finally:
        root.chmod(0o755)


def test_space_in_path_handled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_root(tmp_path)
    assert " " in str(root)
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))
    assert get_data_root() == root.resolve()


def test_project_dir_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_root(tmp_path, "terrascope")
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))

    assert resolve_project_data_dir("terrascope") == (root / "terrascope").resolve()


def test_unknown_project_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(tmp_path))
    with pytest.raises(ValueError, match="Unknown project"):
        resolve_project_data_dir("../../../etc")


def test_missing_project_subtree_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "data root"
    root.mkdir()
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))

    with pytest.raises(DataRootUnavailableError):
        resolve_project_data_dir("shared", create=False)

    created = resolve_project_data_dir("shared", create=True)
    assert created == (root / "shared").resolve()
    assert created.is_dir()


def test_check_data_root_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _make_root(tmp_path, "terrascope", "finguard")
    monkeypatch.setenv(DATA_ROOT_ENV_VAR, str(root))

    status = check_data_root()
    assert status.source == "environment"
    assert status.present_projects == ("terrascope", "finguard")
    assert status.missing_projects == ("shared",)
    assert status.free_bytes is not None
    # "Healthy" requires the full dataset layout, so a missing subtree
    # keeps the status unhealthy even though the root itself is usable.
    assert status.healthy is False

    (root / "shared").mkdir()
    assert check_data_root().healthy is True


def test_find_repo_root_walks_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    nested = repo / "packages" / "x"
    nested.mkdir(parents=True)
    (repo / ".python-version").write_text("3.13\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.chdir(nested)

    assert find_repo_root() == repo.resolve()
