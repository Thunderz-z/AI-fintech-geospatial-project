"""API tests for TerraScope (offline via data-root injection)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from terrascope.api.app import create_app


@pytest.fixture()
def artefact_root(tmp_path: Path) -> Path:
    """Minimal artefact tree the API serves (no real data root needed)."""
    water = tmp_path / "processed" / "water-extent"
    water.mkdir(parents=True)
    (water / "water_extent_2019-04-01_2026-10-31_v1.json").write_text(
        json.dumps({"series": [{"date": "2024-01-05", "water_fraction": 0.11}]})
    )
    change = tmp_path / "processed" / "change-detection"
    change.mkdir()
    (change / "change_winter_winter_2019-20_vs_winter.json").write_text(
        json.dumps({"water_fraction_a": 0.2505, "water_fraction_b": 0.2474})
    )
    classification = tmp_path / "processed" / "classification"
    classification.mkdir()
    (classification / "classification_winter_report.json").write_text(
        json.dumps({"mean_accuracy": 0.5897, "sd_accuracy": 0.0322})
    )
    return tmp_path


@pytest.fixture()
def client(artefact_root: Path) -> TestClient:
    return TestClient(create_app(artefact_root))


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_water_series_carries_artefact_path(client: TestClient) -> None:
    payload = client.get("/analysis/water-series").json()
    assert payload["_artefact"] == (
        "processed/water-extent/water_extent_2019-04-01_2026-10-31_v1.json"
    )
    assert payload["series"][0]["water_fraction"] == pytest.approx(0.11)


def test_change_endpoint(client: TestClient) -> None:
    payload = client.get("/analysis/change").json()
    assert payload["water_fraction_a"] == pytest.approx(0.2505)


def test_classification_endpoint(client: TestClient) -> None:
    payload = client.get("/analysis/classification").json()
    assert payload["mean_accuracy"] == pytest.approx(0.5897)


def test_missing_artefact_is_404(client: TestClient) -> None:
    response = client.get("/analysis/classification", params={"season": "summer"})
    assert response.status_code == 404


def test_unavailable_data_root_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    import terrascope.config
    from relia.config.paths import DataRootUnavailableError

    def broken() -> Path:
        raise DataRootUnavailableError("drive unplugged")

    monkeypatch.setattr(terrascope.config, "data_dir", broken)
    client = TestClient(create_app(None))
    response = client.get("/analysis/water-series")
    assert response.status_code == 503
    assert "drive unplugged" in response.json()["detail"]
