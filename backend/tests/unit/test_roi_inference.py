from PIL import Image
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from app.services.roi_inference import box_within_roi, mask_tile_to_roi
from app.services.geometry_service import build_grid


def test_mask_uses_mosaic_offsets_and_pixel_centers():
    roi = Polygon([(105, 205), (115, 205), (105, 215)])
    image = Image.new("RGB", (20, 20), (10, 20, 30))
    mask_tile_to_roi(image, roi, 100, 200)
    assert image.getpixel((6, 6)) == (10, 20, 30)
    assert image.getpixel((14, 14)) == (0, 0, 0)
    assert image.getpixel((0, 0)) == (0, 0, 0)


def test_mask_preserves_multiple_rois_and_masks_holes():
    polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                      holes=[[(3, 3), (7, 3), (7, 7), (3, 7)]])
    roi = unary_union([polygon, box(15, 0, 20, 5)])
    image = Image.new("RGB", (20, 10), "white")
    mask_tile_to_roi(image, roi, 0, 0)
    assert image.getpixel((1, 1)) == (255, 255, 255)
    assert image.getpixel((16, 1)) == (255, 255, 255)
    assert image.getpixel((5, 5)) == (0, 0, 0)
    assert image.getpixel((12, 1)) == (0, 0, 0)


def test_box_filter_rejects_outside_crossing_and_concave_gap():
    roi = Polygon([(0, 0), (100, 0), (100, 30), (30, 30), (30, 100), (0, 100)])
    assert box_within_roi((0, 0, 20, 20), roi)
    assert not box_within_roi((110, 0, 120, 10), roi)
    assert not box_within_roi((20, 20, 40, 40), roi)
    assert not box_within_roi((50, 50, 70, 70), roi)


def test_zero_threshold_never_admits_non_intersecting_tiles():
    roi = box(20, 20, 40, 40)
    tiles, _ = build_grid([roi], source_width=1000, source_height=1000,
                         tile_size=320, overlap=0, min_roi_intersection=0)
    assert tiles
    assert all(tile.roi_intersection > 0 for tile in tiles)
