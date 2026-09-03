from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.domain.schemas import StrictSchema


class InferenceJobCreate(StrictSchema):
    grid_plan_id: str
    model_version_id: str | None = None
    provider: Literal["auto", "fake", "yolov13", "yolo11"] = "auto"
    infer_min_confidence: float = Field(default=0.20, ge=0, le=1)
    review_threshold: float = Field(default=0.50, ge=0, le=1)
    auto_accept_threshold: float = Field(default=0.80, ge=0, le=1)
    nms_iou: float = Field(default=0.45, gt=0, le=1)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "InferenceJobCreate":
        if not (
            self.infer_min_confidence
            <= self.review_threshold
            <= self.auto_accept_threshold
        ):
            raise ValueError(
                "infer_min_confidence <= review_threshold <= auto_accept_threshold"
            )
        return self


class BoxRead(StrictSchema):
    x1: float
    y1: float
    x2: float
    y2: float


class PointRead(StrictSchema):
    x: float
    y: float


class CategoryRead(StrictSchema):
    id: int
    name: str


class DetectionRead(StrictSchema):
    id: str
    code: str
    run_id: str
    category: CategoryRead
    confidence: float = Field(ge=0, le=1)
    tile_box: BoxRead
    mosaic_box: BoxRead
    center: PointRead
    source_grid: str
    auto_state: str
    review_state: str
    effective_state: str
    version: int = Field(ge=1)
    crop_artifact_id: str | None = None
    created_at: datetime


class DetectionList(StrictSchema):
    run_id: str | None
    run_status: str | None
    thresholds: dict[str, float]
    stats: dict[str, int]
    review_snapshot_version: int = Field(ge=0)
    items: list[DetectionRead]
    next_cursor: str | None = None


class ReviewUpdate(StrictSchema):
    action: Literal["accept", "reject", "reset"]
    comment: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)


class ReviewResult(StrictSchema):
    detection: DetectionRead
    stats: dict[str, int]
    review_snapshot_version: int = Field(ge=0)
    invalidated: list[str]
