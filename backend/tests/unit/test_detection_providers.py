from pathlib import Path

from app.adapters.detection import create_detector
from app.adapters.detection.yolo11 import Yolo11Detector
from app.adapters.detection.yolov13 import YoloV13Detector
from app.api.routes import health
from app.core.config import Settings
from app.domain.inference_schemas import InferenceJobCreate


def _settings(weights: Path, provider: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        mosaic_provider="fake",
        detector_provider=provider,
        model_weights_path=weights,
        model_device="cpu",
    )


def test_detector_factory_keeps_yolov13_and_adds_yolo11(tmp_path: Path) -> None:
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"test-only-placeholder")

    yolov13 = create_detector("yolov13", _settings(weights, "yolov13"))
    yolo11 = create_detector("yolo11", _settings(weights, "yolo11"))

    assert isinstance(yolov13, YoloV13Detector)
    assert yolov13.provider == "yolov13"
    assert isinstance(yolo11, Yolo11Detector)
    assert yolo11.provider == "yolo11"


def test_inference_contract_accepts_yolo11() -> None:
    request = InferenceJobCreate(grid_plan_id="grid-1", provider="yolo11")
    assert request.provider == "yolo11"


def test_yolo11_readiness_uses_ultralytics_runtime(
    tmp_path: Path, monkeypatch
) -> None:
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"test-only-placeholder")
    settings = _settings(weights, "yolo11")
    monkeypatch.setattr(health, "installed_ultralytics_version", lambda: "8.4.117")

    checks, ready = health._provider_checks(settings)

    assert ready is True
    assert checks["detector_provider"] == {
        "name": "yolo11",
        "configured": True,
        "runtime_version": "8.4.117",
    }
