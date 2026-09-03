from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from PIL import Image


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    name: str
    provider: str
    weights_sha256: str
    weights_label: str
    input_size: int
    class_map: dict[int, str]
    device: str
    code_version: str
    metadata: dict[str, object]


@dataclass(frozen=True, slots=True)
class ImageInput:
    tile_id: str
    tile_code: str
    image: Image.Image


@dataclass(frozen=True, slots=True)
class DetectParams:
    min_confidence: float
    input_size: int = 640


@dataclass(frozen=True, slots=True)
class RawPrediction:
    tile_id: str
    tile_code: str
    class_id: int
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]


class DetectorError(Exception):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class Detector(Protocol):
    def metadata(self) -> ModelMetadata: ...

    def warmup(self) -> None: ...

    def predict(
        self,
        images: Sequence[ImageInput],
        params: DetectParams,
    ) -> list[RawPrediction]: ...
