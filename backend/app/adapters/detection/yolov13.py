from __future__ import annotations

from pathlib import Path

from app.adapters.detection.ultralytics import (
    UltralyticsDetector,
    installed_ultralytics_version,
)


class YoloV13Detector(UltralyticsDetector):
    """Provider identity for a server-configured YOLOv13 checkpoint."""

    def __init__(
        self,
        weights_path: Path | None,
        device: str,
        *,
        input_size: int = 640,
        required_ultralytics_version: str | None = None,
    ) -> None:
        super().__init__(
            weights_path,
            device,
            provider="yolov13",
            display_name="MosquitoMapper YOLOv13 detector",
            input_size=input_size,
            required_ultralytics_version=required_ultralytics_version,
        )


__all__ = ["YoloV13Detector", "installed_ultralytics_version"]
