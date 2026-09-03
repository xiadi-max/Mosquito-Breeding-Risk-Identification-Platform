from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.adapters.mosaic import opencv as opencv_module
from app.adapters.mosaic.base import MosaicSource
from app.adapters.mosaic.opencv import OpenCVMosaicEngine


def _write_png(path: Path, value: int) -> None:
    image = np.full((20, 30, 3), value, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    encoded.tofile(str(path))


def test_scans_engine_uses_unicode_safe_decode_scale_crop_and_jpeg(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "航拍_02.png"
    second = tmp_path / "航拍_01.png"
    _write_png(first, 80)
    _write_png(second, 160)

    class FakeStitcher:
        def stitch(self, images):
            assert len(images) == 2
            assert all(image.shape == (10, 15, 3) for image in images)
            canvas = np.zeros((16, 28, 3), dtype=np.uint8)
            canvas[2:14, 3:25] = 120
            return cv2.Stitcher_OK, canvas

    captured = {}

    def fake_create(threshold: float):
        captured["threshold"] = threshold
        return FakeStitcher()

    monkeypatch.setattr(opencv_module, "_create_scans_stitcher", fake_create)
    sources = [
        MosaicSource("two", first, "b", False, first.name),
        MosaicSource("one", second, "a", True, second.name),
    ]
    events = []
    result = OpenCVMosaicEngine(work_scale=0.5).run(
        sources,
        tmp_path / "output",
        {},
        lambda value, step, message: events.append((value, step, message)),
        lambda: False,
    )

    assert captured["threshold"] == 0.3
    assert result.mosaic_path.name == "mosaic.jpg"
    assert result.mosaic_path.read_bytes().startswith(b"\xff\xd8\xff")
    assert result.mosaic_mime_type == "image/jpeg"
    assert (result.width, result.height) == (22, 12)
    assert result.quality_summary["strategy"] == "opencv_scans_affine"
    assert result.quality_summary["black_border_cropped"] is True
    assert result.quality_summary["source_preprocessing"] == "none"
    assert result.quality_summary["gps_count"] == 1
    assert any(step == "feature_registration" for _, step, _ in events)


def test_crop_black_border_keeps_an_all_black_image() -> None:
    image = np.zeros((8, 9, 3), dtype=np.uint8)
    cropped, changed = opencv_module._crop_black_border(image, threshold=2)
    assert cropped.shape == image.shape
    assert changed is False
