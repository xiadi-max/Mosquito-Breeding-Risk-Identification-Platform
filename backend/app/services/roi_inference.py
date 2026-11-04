"""Apply the saved ROI to model inputs and final detection boxes."""

import numpy as np
from PIL import Image
from shapely import intersects_xy
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry


def mask_tile_to_roi(image: Image.Image, roi: BaseGeometry, offset_x: float, offset_y: float) -> None:
    """Black out pixels whose centers are outside the ROI, in mosaic coordinates."""
    width, height = image.size
    if roi.covers(box(offset_x, offset_y, offset_x + width, offset_y + height)):
        return
    xs = np.arange(width, dtype=float) + offset_x + 0.5
    ys = np.arange(height, dtype=float) + offset_y + 0.5
    inside = intersects_xy(roi, xs[None, :], ys[:, None])
    mask = Image.fromarray(np.where(inside, 0, 255).astype(np.uint8))
    image.paste((0, 0, 0), (0, 0, width, height), mask)
    mask.close()


def box_within_roi(bounds: tuple[float, float, float, float], roi: BaseGeometry) -> bool:
    """Keep only boxes fully covered by the union of visible, saved ROIs."""
    return bool(roi.covers(box(*bounds)))
