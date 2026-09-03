from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class MappedPrediction:
    tile_id: str
    tile_code: str
    class_id: int
    class_name: str
    confidence: float
    tile_box: Box
    mosaic_box: Box


def inverse_letterbox(
    box: Box,
    *,
    scale: float,
    pad_x: float,
    pad_y: float,
    source_width: int,
    source_height: int,
) -> Box:
    if scale <= 0:
        raise ValueError("letterbox scale must be positive")
    x1, y1, x2, y2 = box
    return clip_box(
        ((x1 - pad_x) / scale, (y1 - pad_y) / scale, (x2 - pad_x) / scale, (y2 - pad_y) / scale),
        source_width,
        source_height,
    )


def tile_box_to_mosaic(
    box: Box,
    *,
    scale_x: float,
    scale_y: float,
    offset_x: float,
    offset_y: float,
    mosaic_width: int,
    mosaic_height: int,
) -> Box:
    x1, y1, x2, y2 = box
    return clip_box(
        (
            x1 * scale_x + offset_x,
            y1 * scale_y + offset_y,
            x2 * scale_x + offset_x,
            y2 * scale_y + offset_y,
        ),
        mosaic_width,
        mosaic_height,
    )


def clip_box(box: Box, width: int, height: int) -> Box:
    x1, y1, x2, y2 = box
    clipped = (
        min(float(width), max(0.0, x1)),
        min(float(height), max(0.0, y1)),
        min(float(width), max(0.0, x2)),
        min(float(height), max(0.0, y2)),
    )
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        raise ValueError("box is empty after clipping")
    return clipped


def box_iou(left: Box, right: Box) -> float:
    ix1, iy1 = max(left[0], right[0]), max(left[1], right[1])
    ix2, iy2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = (left[2] - left[0]) * (left[3] - left[1])
    right_area = (right[2] - right[0]) * (right[3] - right[1])
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def class_aware_nms(
    predictions: Iterable[MappedPrediction], iou_threshold: float
) -> list[MappedPrediction]:
    ordered = sorted(predictions, key=lambda item: (-item.confidence, item.tile_code, item.class_id))
    kept: list[MappedPrediction] = []
    for candidate in ordered:
        if any(
            existing.class_id == candidate.class_id
            and box_iou(existing.mosaic_box, candidate.mosaic_box) > iou_threshold
            for existing in kept
        ):
            continue
        kept.append(candidate)
    return kept
