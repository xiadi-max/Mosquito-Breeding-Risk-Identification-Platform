from __future__ import annotations

import hashlib
import importlib.util
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Sequence

from app.adapters.detection.base import (
    DetectParams,
    DetectorError,
    ImageInput,
    ModelMetadata,
    RawPrediction,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def installed_ultralytics_version() -> str | None:
    """Return the installed runtime version without importing model code."""

    if importlib.util.find_spec("ultralytics") is None:
        return None
    try:
        return importlib_metadata.version("ultralytics")
    except importlib_metadata.PackageNotFoundError:
        # Editable checkouts still expose __version__, but importing model code
        # belongs in the model loading path rather than readiness probes.
        return "editable-or-unknown"


class UltralyticsDetector:
    """Shared detector implementation for server-controlled Ultralytics weights."""

    def __init__(
        self,
        weights_path: Path | None,
        device: str,
        *,
        provider: str,
        display_name: str,
        input_size: int = 640,
        required_ultralytics_version: str | None = None,
    ) -> None:
        if weights_path is None:
            raise DetectorError("MODEL_NOT_CONFIGURED", "未配置 MODEL_WEIGHTS_PATH。")
        path = weights_path.expanduser().resolve()
        if not path.is_file():
            raise DetectorError("MODEL_NOT_CONFIGURED", "配置的模型权重文件不存在。")
        self.path = path
        self.device = device
        self.provider = provider
        self.display_name = display_name
        self.input_size = input_size
        self.required_ultralytics_version = required_ultralytics_version
        self._model = None
        self._runtime_version: str | None = None

    def _load(self):
        if self._model is None:
            try:
                import ultralytics
                from ultralytics import YOLO
            except ImportError as exc:
                raise DetectorError(
                    "MODEL_NOT_CONFIGURED",
                    "YOLO Provider 需要安装与权重兼容的 ultralytics 包。",
                ) from exc
            runtime_version = str(getattr(ultralytics, "__version__", "unknown"))
            if (
                self.required_ultralytics_version
                and runtime_version != self.required_ultralytics_version
            ):
                raise DetectorError(
                    "MODEL_RUNTIME_INCOMPATIBLE",
                    "当前 ultralytics 版本与模型要求不一致："
                    f"需要 {self.required_ultralytics_version}，实际 {runtime_version}。",
                )
            try:
                self._model = YOLO(str(self.path))
                self._runtime_version = runtime_version
            except Exception as exc:
                raise DetectorError("MODEL_LOAD_FAILED", "YOLO 权重加载失败。") from exc
        return self._model

    def metadata(self) -> ModelMetadata:
        model = self._load()
        names = getattr(model, "names", {})
        class_map = {int(key): str(value) for key, value in dict(names).items()}
        return ModelMetadata(
            name=self.display_name,
            provider=self.provider,
            weights_sha256=_sha256(self.path),
            weights_label=self.path.name,
            input_size=self.input_size,
            class_map=class_map,
            device=self.device,
            code_version=f"ultralytics-{self._runtime_version};adapter-v2",
            metadata={
                "framework": "ultralytics",
                "runtime_version": self._runtime_version,
                "required_runtime_version": self.required_ultralytics_version,
            },
        )

    def warmup(self) -> None:
        self._load()

    def predict(
        self,
        images: Sequence[ImageInput],
        params: DetectParams,
    ) -> list[RawPrediction]:
        model = self._load()
        try:
            results = model.predict(
                source=[item.image for item in images],
                imgsz=params.input_size,
                conf=params.min_confidence,
                device=self.device,
                verbose=False,
            )
            metadata = self.metadata()
            predictions: list[RawPrediction] = []
            for item, result in zip(images, results, strict=True):
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue
                for xyxy, confidence, class_id in zip(
                    boxes.xyxy.cpu().tolist(),
                    boxes.conf.cpu().tolist(),
                    boxes.cls.cpu().tolist(),
                    strict=True,
                ):
                    class_value = int(class_id)
                    predictions.append(
                        RawPrediction(
                            tile_id=item.tile_id,
                            tile_code=item.tile_code,
                            class_id=class_value,
                            class_name=metadata.class_map.get(
                                class_value, f"class-{class_value}"
                            ),
                            confidence=float(confidence),
                            box=tuple(float(value) for value in xyxy),
                        )
                    )
            return predictions
        except DetectorError:
            raise
        except Exception as exc:
            raise DetectorError("INFERENCE_FAILED", "YOLO 推理执行失败。") from exc
