from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
from typing import Iterable

from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.validation import explain_validity

from app.core.errors import AppError
from app.core.fingerprint import fingerprint


Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class ValidatedPolygon:
    points: list[Point]
    geometry: Polygon
    area_px2: float


@dataclass(frozen=True, slots=True)
class GridTileSpec:
    code: str
    source_box: tuple[int, int, int, int]
    padding: tuple[int, int, int, int]
    tile_to_mosaic: dict[str, float]
    roi_intersection: float


def validate_polygon(points: Iterable[Point], width: int, height: int) -> ValidatedPolygon:
    normalized = [(float(x), float(y)) for x, y in points]
    if len(normalized) > 1 and normalized[0] == normalized[-1]:
        normalized.pop()
    distinct = set(normalized)
    if len(distinct) < 3:
        _invalid("ROI 至少需要 3 个不同顶点。")
    for x, y in normalized:
        if x < 0 or y < 0 or x > width or y > height:
            _invalid(f"ROI 坐标必须位于拼接图范围 0..{width} × 0..{height} 内。")
    polygon = Polygon(normalized)
    if polygon.is_empty or polygon.area <= 0:
        _invalid("ROI 面积必须大于 0。")
    if not polygon.is_valid:
        _invalid(f"ROI 多边形无效：{explain_validity(polygon)}。")
    return ValidatedPolygon(normalized, polygon, float(polygon.area))


def svg_to_native(
    x: float,
    y: float,
    *,
    viewbox_width: float,
    viewbox_height: float,
    source_width: int,
    source_height: int,
) -> Point:
    return (
        x / viewbox_width * source_width,
        y / viewbox_height * source_height,
    )


def native_to_svg(
    x: float,
    y: float,
    *,
    viewbox_width: float,
    viewbox_height: float,
    source_width: int,
    source_height: int,
) -> Point:
    return (
        x / source_width * viewbox_width,
        y / source_height * viewbox_height,
    )


def build_grid(
    polygons: list[Polygon],
    *,
    source_width: int,
    source_height: int,
    tile_size: int,
    overlap: float,
    min_roi_intersection: float,
) -> tuple[list[GridTileSpec], int]:
    if not polygons:
        raise AppError(
            status_code=400,
            code="INVALID_WORKFLOW_STATE",
            title="缺少 ROI",
            detail="至少保存一个 ROI 后才能生成网格。",
        )
    roi_geometry = unary_union(polygons)
    min_x, min_y, max_x, max_y = roi_geometry.bounds
    step = round(tile_size * (1 - overlap))
    start_x = floor(min_x / step) * step
    start_y = floor(min_y / step) * step
    stop_x = ceil(max_x / step) * step
    stop_y = ceil(max_y / step) * step
    tiles: list[GridTileSpec] = []
    for y in range(start_y, stop_y + 1, step):
        for x in range(start_x, stop_x + 1, step):
            nominal = box(x, y, x + tile_size, y + tile_size)
            intersection_area = roi_geometry.intersection(nominal).area
            ratio = intersection_area / float(tile_size * tile_size)
            if ratio + 1e-12 < min_roi_intersection:
                continue
            source_x1 = max(0, x)
            source_y1 = max(0, y)
            source_x2 = min(source_width, x + tile_size)
            source_y2 = min(source_height, y + tile_size)
            if source_x1 >= source_x2 or source_y1 >= source_y2:
                continue
            padding = (
                max(0, -x),
                max(0, -y),
                max(0, x + tile_size - source_width),
                max(0, y + tile_size - source_height),
            )
            code = f"G{len(tiles) + 1:03d}"
            tiles.append(
                GridTileSpec(
                    code=code,
                    source_box=(source_x1, source_y1, source_x2, source_y2),
                    padding=padding,
                    tile_to_mosaic={
                        "scale_x": 1.0,
                        "scale_y": 1.0,
                        "offset_x": float(source_x1 - padding[0]),
                        "offset_y": float(source_y1 - padding[1]),
                    },
                    roi_intersection=round(min(1.0, max(0.0, ratio)), 8),
                )
            )
    return tiles, step


def grid_fingerprint_payload(
    *,
    roi_fingerprint: str,
    mosaic_artifact_id: str,
    tile_size: int,
    overlap: float,
    step_px: int,
    min_roi_intersection: float,
    tiles: list[GridTileSpec],
) -> dict:
    return {
        "operation": "grid_generate",
        "roi_fingerprint": roi_fingerprint,
        "mosaic_artifact_id": mosaic_artifact_id,
        "tile_size": tile_size,
        "overlap": overlap,
        "step_px": step_px,
        "edge_strategy": "pad",
        "min_roi_intersection": min_roi_intersection,
        "tiles": [
            {
                "code": tile.code,
                "source_box": tile.source_box,
                "padding": tile.padding,
                "roi_intersection": tile.roi_intersection,
            }
            for tile in tiles
        ],
    }


def grid_fingerprint(**kwargs) -> str:
    return fingerprint(grid_fingerprint_payload(**kwargs))


def _invalid(detail: str) -> None:
    raise AppError(
        status_code=400,
        code="INVALID_POLYGON",
        title="ROI 多边形无效",
        detail=detail,
    )
