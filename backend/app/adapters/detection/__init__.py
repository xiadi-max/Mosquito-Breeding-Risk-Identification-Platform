"""Detection provider adapters."""
from __future__ import annotations

from app.adapters.detection.base import Detector
from app.adapters.detection.fake import FakeDetector
from app.adapters.detection.yolo11 import Yolo11Detector
from app.adapters.detection.yolov13 import YoloV13Detector
from app.core.config import Settings


def create_detector(provider: str, settings: Settings) -> Detector:
    if provider == "fake":
        return FakeDetector(settings.model_device)
    if provider == "yolov13":
        return YoloV13Detector(
            settings.model_weights_path,
            settings.model_device,
            input_size=settings.model_input_size,
            required_ultralytics_version=settings.model_required_ultralytics_version,
        )
    if provider == "yolo11":
        return Yolo11Detector(
            settings.model_weights_path,
            settings.model_device,
            input_size=settings.model_input_size,
            required_ultralytics_version=settings.model_required_ultralytics_version,
        )
    raise ValueError(f"unsupported detector provider: {provider}")


__all__ = ["create_detector"]
