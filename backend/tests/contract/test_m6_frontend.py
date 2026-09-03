from __future__ import annotations


def test_frontend_is_served_in_api_mode(client):
    page = client.get("/")
    assert page.status_code == 200
    assert '<script src="./frontend-config.js"></script>' in page.text
    assert "api-integration.js" in page.text

    config = client.get("/frontend-config.js")
    assert config.status_code == 200
    assert '"apiBaseUrl": "/api/v1"' in config.text
    assert '"demoAllowed": true' in config.text

    assert client.get("/data.js").status_code == 200
    assert client.get("/api-client.js").status_code == 200
    assert client.get("/api-integration.js").status_code == 200


def test_frontend_asset_allowlist_rejects_paths(client):
    assert client.get("/pyproject.toml").status_code == 404
    assert client.get("/..%2Fbackend%2F.env").status_code in {404, 422}


def test_production_frontend_disables_demo_data(test_settings):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app

    values = test_settings.model_dump()
    values["app_env"] = "production"
    with TestClient(create_app(Settings(_env_file=None, **values))) as client:
        config = client.get("/frontend-config.js")
        assert config.status_code == 200
        assert '"demoAllowed": false' in config.text
        assert client.get("/test_data.js").status_code == 404


def test_frontend_scripts_have_no_fake_business_timers():
    from app.api.routes.frontend import FRONTEND_ROOT

    integration = (FRONTEND_ROOT / "api-integration.js").read_text(encoding="utf-8")
    assert "setInterval(" not in integration
    assert "structuredClone(window.TEST_DATA)" not in integration
    assert "innerHTML=`" not in integration
    assert "resetApiBusinessPanels()" in integration
    assert "REAL DATA" in integration
    assert "job.status==='succeeded'" in integration
    assert "风险批次" not in integration
    assert "重点检查区域" in integration
    assert "目标聚集指数" in integration
    assert "区域密度" not in integration
    assert "10万像素" not in integration
    assert "setAttributeNS(SVG_XLINK" in integration
    assert "knownMosaicArtifactId" in integration
    assert "document.body.appendChild(badge)" not in integration
    assert "priority.body.split" in integration
