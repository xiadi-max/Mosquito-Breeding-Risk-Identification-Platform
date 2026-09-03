import pytest

from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.integration
def test_live_ready_and_version_contract(client) -> None:
    live = client.get("/api/v1/health/live")
    ready = client.get("/api/v1/health/ready")
    version = client.get("/api/v1/version")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert live.headers["x-request-id"].startswith("req_")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["checks"]["database"] == "ok"
    assert ready.json()["checks"]["storage"] == "ok"

    assert version.status_code == 200
    assert version.json()["application"] == "MosquitoMapper Backend"
    assert version.json()["providers"]["mosaic"]["name"] == "fake"
    assert "model_weights_path" not in version.text


@pytest.mark.integration
def test_client_request_id_is_echoed(client) -> None:
    response = client.get(
        "/api/v1/health/live", headers={"X-Request-ID": "frontend-request-1"}
    )
    assert response.headers["x-request-id"] == "frontend-request-1"


@pytest.mark.integration
def test_production_fake_providers_are_not_reported_ready(test_settings) -> None:
    production = test_settings.model_copy(update={"app_env": "production"})
    with TestClient(create_app(production)) as client:
        ready = client.get("/api/v1/health/ready")
        version = client.get("/api/v1/version")

    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["checks"]["mosaic_provider"]["configured"] is False
    assert ready.json()["checks"]["detector_provider"]["configured"] is False
    assert version.json()["providers"]["mosaic"]["configured"] is False
    assert version.json()["providers"]["detector"]["configured"] is False
