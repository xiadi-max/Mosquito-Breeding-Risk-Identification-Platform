from __future__ import annotations

from pathlib import Path

import pytest
import requests
from PIL import Image

from app.adapters.mosaic import create_mosaic_engine
from app.adapters.mosaic.base import MosaicSource
from app.adapters.mosaic.webodm import (
    WebODMClient,
    WebODMMosaicEngine,
    WebODMResponseError,
    webodm_configuration_ready,
)
from app.core.config import Settings


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "mosaic_provider": "webodm",
        "webodm_url": "https://odm.example.test",
        "webodm_username": "tester",
        "webodm_password": "secret",
    }
    values.update(overrides)
    return Settings(**values)


def test_webodm_configuration_and_factory() -> None:
    settings = _settings()
    assert webodm_configuration_ready(settings) is True
    assert isinstance(create_mosaic_engine("webodm", settings), WebODMMosaicEngine)
    assert webodm_configuration_ready(_settings(webodm_password="")) is False


def test_webodm_engine_submits_polls_downloads_and_renders(
    tmp_path: Path, monkeypatch
) -> None:
    source_paths = [tmp_path / "航拍01.jpg", tmp_path / "航拍02.jpg"]
    for index, path in enumerate(source_paths):
        Image.new("RGB", (80, 60), (20 + index * 30, 70, 90)).save(path)
    sources = [
        MosaicSource(str(index), path, str(index), index == 0, path.name)
        for index, path in enumerate(source_paths)
    ]
    captured = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            captured["client"] = (args, kwargs)
            self.poll_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def find_project(self, name):
            captured["project_name"] = name
            return None

        def create_project(self, name, description):
            captured["project_description"] = description
            return 7

        def find_task(self, project_id, name):
            captured["task_name"] = name
            return None

        def create_task(self, project_id, submitted, *, name, orthophoto_resolution):
            captured["resolution"] = orthophoto_resolution
            captured["source_count"] = len(submitted)
            return 9

        def get_task(self, project_id, task_id):
            self.poll_count += 1
            if self.poll_count == 1:
                return {"status": 20, "running_progress": 0.5}
            return {
                "status": 40,
                "available_assets": ["orthophoto.tif", "orthophoto.png"],
            }

        def download_asset(self, project_id, task_id, asset, output_path):
            if asset.endswith(".png"):
                Image.new("RGBA", (120, 90), (10, 40, 70, 255)).save(output_path)
            else:
                output_path.write_bytes(b"test-geotiff")
            return output_path

        def cancel_task(self, project_id, task_id):
            captured["canceled"] = True

    monkeypatch.setattr("app.adapters.mosaic.webodm.WebODMClient", FakeClient)
    monkeypatch.setattr("app.adapters.mosaic.webodm.time.sleep", lambda _: None)
    events = []
    engine = create_mosaic_engine("webodm", _settings(webodm_poll_seconds=1))
    result = engine.run(
        sources,
        tmp_path / "tasks" / "local-task" / "tmp" / "local-job",
        {"orthophoto_resolution": 2.5},
        lambda value, step, message: events.append((value, step, message)),
        lambda: False,
    )

    assert captured["project_name"] == "MosquitoMapper-local-task"
    assert captured["task_name"] == "拼接-local-job"
    assert captured["resolution"] == 2.5
    assert captured["source_count"] == 2
    assert result.mosaic_path.read_bytes().startswith(b"\xff\xd8\xff")
    assert result.preview_path.is_file()
    assert (result.width, result.height) == (120, 90)
    assert result.extra_artifacts[0].path.read_bytes() == b"test-geotiff"
    assert result.quality_summary["webodm_project_id"] == 7
    assert result.quality_summary["webodm_task_id"] == 9
    assert any(step == "webodm_processing" for _, step, _ in events)


def test_webodm_engine_requires_credentials() -> None:
    engine = create_mosaic_engine("webodm", _settings(webodm_password=""))
    with pytest.raises(Exception, match="地址、用户名或密码"):
        engine.validate()


def test_webodm_gateway_error_has_recovery_guidance() -> None:
    response = requests.Response()
    response.status_code = 502
    response._content = b""
    client = WebODMClient(
        "https://odm.example.test",
        "tester",
        "secret",
        verify_ssl=True,
        request_timeout_seconds=60,
    )
    try:
        with pytest.raises(WebODMResponseError) as caught:
            client._expect_ok(response, "登录 WebODM")
    finally:
        client.close()

    assert caught.value.code == "WEBODM_UNAVAILABLE"
    assert caught.value.retryable is True
    assert "启动或重启 WebODM" in caught.value.detail
    assert "本地 OpenCV" in caught.value.detail
