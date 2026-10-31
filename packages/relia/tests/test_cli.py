"""Tests for the RELIA CLI (relia.cli)."""

import pytest

from relia.cli import main


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from relia.config.paths import DATA_ROOT_ENV_VAR

    monkeypatch.delenv(DATA_ROOT_ENV_VAR, raising=False)


def test_check_data_root_healthy(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "data root"
    for project in ("terrascope", "finguard", "shared"):
        (root / project).mkdir(parents=True)
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))

    exit_code = main(["check-data-root"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Healthy:" in out
    assert "True" in out
    assert "present=terrascope, finguard, shared" in out


def test_check_data_root_missing_config(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["check-data-root"])

    err = capsys.readouterr().err
    assert exit_code == 1
    assert "ERROR" in err


def test_check_data_root_unhealthy_reports_and_fails(tmp_path, monkeypatch, capsys) -> None:
    root = tmp_path / "data root"
    root.mkdir()  # exists and writable, but no project subdirectories
    monkeypatch.setenv("PORTFOLIO_DATA_ROOT", str(root))

    exit_code = main(["check-data-root"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Healthy:" in out
    assert "False" in out
    assert "missing=terrascope, finguard, shared" in out
