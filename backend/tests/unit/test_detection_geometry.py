from __future__ import annotations

import pytest

from app.services.detection_geometry import (
    MappedPrediction,
    box_iou,
    class_aware_nms,
    inverse_letterbox,
    tile_box_to_mosaic,
)


def prediction(class_id: int, confidence: float, box, tile="G001"):
    return MappedPrediction(
        tile_id=tile,
        tile_code=tile,
        class_id=class_id,
        class_name=f"class-{class_id}",
        confidence=confidence,
        tile_box=box,
        mosaic_box=box,
    )


def test_inverse_letterbox_and_tile_mapping_clip_to_mosaic() -> None:
    tile_box = inverse_letterbox(
        (20, 40, 220, 240),
        scale=2,
        pad_x=20,
        pad_y=40,
        source_width=100,
        source_height=100,
    )
    assert tile_box == (0, 0, 100, 100)
    mosaic_box = tile_box_to_mosaic(
        tile_box,
        scale_x=1,
        scale_y=1,
        offset_x=950,
        offset_y=850,
        mosaic_width=1000,
        mosaic_height=900,
    )
    assert mosaic_box == (950, 850, 1000, 900)


def test_class_aware_nms_suppresses_same_class_only() -> None:
    candidates = [
        prediction(0, 0.9, (0, 0, 100, 100), "G001"),
        prediction(0, 0.8, (10, 10, 110, 110), "G002"),
        prediction(1, 0.7, (10, 10, 110, 110), "G002"),
    ]
    assert box_iou(candidates[0].mosaic_box, candidates[1].mosaic_box) > 0.45
    kept = class_aware_nms(candidates, 0.45)
    assert [(item.class_id, item.confidence) for item in kept] == [(0, 0.9), (1, 0.7)]


def test_empty_box_after_mapping_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        tile_box_to_mosaic(
            (0, 0, 10, 10),
            scale_x=1,
            scale_y=1,
            offset_x=-20,
            offset_y=-20,
            mosaic_width=100,
            mosaic_height=100,
        )
