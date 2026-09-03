from __future__ import annotations

from typing import Sequence

from app.adapters.detection.base import (
    DetectParams,
    ImageInput,
    ModelMetadata,
    RawPrediction,
)


class FakeDetector:
    """Deterministic detector for tests and explicitly marked demo environments."""

    def __init__(self, device: str = "cpu") -> None:
        self.device = device

    def metadata(self) -> ModelMetadata:
        return ModelMetadata(
            name="MosquitoMapper deterministic fake detector",
            provider="fake",
            weights_sha256="0" * 64,
            weights_label="built-in-fake",
            input_size=640,
            class_map={0: "积水容器", 1: "轮胎"},
            device=self.device,
            code_version="fake-v1",
            metadata={"demo": True, "measurement_grade": False},
        )

    def warmup(self) -> None:
        return None

    def predict(
        self,
        images: Sequence[ImageInput],
        params: DetectParams,
    ) -> list[RawPrediction]:
        predictions: list[RawPrediction] = []
        for index, item in enumerate(images):
            # Two retained states plus one intentionally sub-threshold prediction.
            for class_id, confidence, box in (
                (0, 0.92, (120.0, 110.0, 250.0, 260.0)),
                (1, 0.64, (330.0, 300.0, 455.0, 435.0)),
                (0, 0.12, (470.0, 80.0, 520.0, 145.0)),
            ):
                if confidence >= params.min_confidence:
                    predictions.append(
                        RawPrediction(
                            tile_id=item.tile_id,
                            tile_code=item.tile_code,
                            class_id=class_id,
                            class_name=self.metadata().class_map[class_id],
                            confidence=confidence - index * 0.001,
                            box=box,
                        )
                    )
        return predictions
