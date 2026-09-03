from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


ProgressCallback = Callable[[int, str, str], None]
CancelCheck = Callable[[], bool]


class MosaicEngineError(Exception):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class MosaicCanceled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class MosaicSource:
    image_id: str
    path: Path
    sha256: str
    has_gps: bool
    display_name: str = ""


@dataclass(slots=True)
class MosaicResult:
    mosaic_path: Path
    preview_path: Path
    width: int
    height: int
    quality_summary: dict[str, Any] = field(default_factory=dict)
    mosaic_filename: str = "mosaic.png"
    mosaic_mime_type: str = "image/png"


class MosaicEngine(Protocol):
    name: str

    def validate(self) -> None: ...

    def run(
        self,
        sources: list[MosaicSource],
        work_directory: Path,
        options: dict[str, Any],
        progress: ProgressCallback,
        is_canceled: CancelCheck,
    ) -> MosaicResult: ...


def raise_if_canceled(is_canceled: CancelCheck) -> None:
    if is_canceled():
        raise MosaicCanceled
