from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.services.geometry_service import (
    build_grid,
    native_to_svg,
    svg_to_native,
    validate_polygon,
)


def test_svg_native_coordinate_round_trip() -> None:
    native = svg_to_native(
        450,
        272.5,
        viewbox_width=900,
        viewbox_height=545,
        source_width=4096,
        source_height=3072,
    )
    assert native == pytest.approx((2048, 1536))
    svg = native_to_svg(
        *native,
        viewbox_width=900,
        viewbox_height=545,
        source_width=4096,
        source_height=3072,
    )
    assert svg == pytest.approx((450, 272.5))


def test_roi_validation_accepts_open_polygon_and_computes_area() -> None:
    result = validate_polygon([(0, 0), (100, 0), (100, 50), (0, 50)], 200, 100)
    assert result.area_px2 == 5000
    assert result.points[0] != result.points[-1]


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (10, 10), (20, 20)],
        [(0, 0), (100, 100), (0, 100), (100, 0)],
        [(-1, 0), (10, 0), (10, 10)],
        [(0, 0), (0, 0), (10, 10)],
    ],
)
def test_roi_validation_rejects_invalid_polygons(points) -> None:
    with pytest.raises(AppError) as error:
        validate_polygon(points, 100, 100)
    assert error.value.code == "INVALID_POLYGON"


def test_grid_step_coverage_and_right_bottom_padding() -> None:
    polygon = validate_polygon([(0, 0), (1000, 0), (1000, 900), (0, 900)], 1000, 900)
    tiles, step = build_grid(
        [polygon.geometry],
        source_width=1000,
        source_height=900,
        tile_size=640,
        overlap=0.20,
        min_roi_intersection=0.10,
    )
    assert step == 512
    assert tiles
    assert any(tile.padding[2] > 0 for tile in tiles)
    assert any(tile.padding[3] > 0 for tile in tiles)
    assert all(tile.source_box[0] >= 0 and tile.source_box[1] >= 0 for tile in tiles)
    assert all(tile.source_box[2] <= 1000 and tile.source_box[3] <= 900 for tile in tiles)

