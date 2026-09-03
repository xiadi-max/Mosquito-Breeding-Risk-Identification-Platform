"""Mosaic provider adapters."""

from app.adapters.mosaic.base import MosaicEngine
from app.adapters.mosaic.fake import FakeMosaicEngine
from app.adapters.mosaic.opencv import OpenCVMosaicEngine
from app.core.config import Settings


def create_mosaic_engine(provider: str, settings: Settings) -> MosaicEngine:
    if provider == "fake":
        return FakeMosaicEngine()
    if provider == "opencv":
        return OpenCVMosaicEngine(
            work_scale=settings.mosaic_work_scale,
            pano_confidence_threshold=settings.mosaic_pano_confidence_threshold,
            black_border_threshold=settings.mosaic_black_border_threshold,
            output_jpeg_quality=settings.mosaic_output_jpeg_quality,
        )
    raise ValueError(f"unknown mosaic provider: {provider}")


__all__ = ["MosaicEngine", "create_mosaic_engine"]
