from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.schemas import StrictSchema


class GridParameters(StrictSchema):
    roi_version: int = Field(ge=1)
    tile_size: Literal[640] = 640
    overlap: float = Field(default=0.20, ge=0, le=0.50)
    edge_strategy: Literal["pad"] = "pad"
    min_roi_intersection: float = Field(default=0.10, gt=0, le=1)


class GridTileRead(StrictSchema):
    code: str
    source_box: tuple[int, int, int, int]
    padding: tuple[int, int, int, int]
    tile_to_mosaic: dict[str, float]
    roi_intersection: float = Field(ge=0, le=1)


class GridPreview(StrictSchema):
    roi_version: int
    source_artifact_id: str
    tile_size: int
    overlap: float
    step_px: int
    edge_strategy: str
    min_roi_intersection: float
    count: int
    padded_count: int
    estimated_bytes: int
    tiles: list[GridTileRead]
    fingerprint: str


class GridPlanCreate(GridParameters):
    fingerprint: str = Field(min_length=64, max_length=64)


class GridPlanRead(StrictSchema):
    id: str
    task_id: str
    roi_version: int
    source_artifact_id: str
    status: Literal["current", "stale"]
    tile_size: int
    overlap: float
    step_px: int
    edge_strategy: str
    min_roi_intersection: float
    count: int
    padded_count: int
    estimated_bytes: int
    fingerprint: str
    tiles: list[GridTileRead]

