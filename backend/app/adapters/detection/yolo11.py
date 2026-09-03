from __future__ import annotations

from pathlib import Path

from app.adapters.detection.ultralytics import UltralyticsDetector


class Yolo11Detector(UltralyticsDetector):
    """Provider identity for a server-configured YOLO11 checkpoint."""

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
            provider="yolo11",
            display_name="MosquitoMapper YOLO11 detector",
            input_size=input_size,
            required_ultralytics_version=required_ultralytics_version,
        )


__all__ = ["Yolo11Detector"]
