from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.domain.schemas import StrictSchema


class GPSInfo(StrictSchema):
    latitude: float
    longitude: float
    altitude_m: float | None = None


class ImageRead(StrictSchema):
    id: str
    artifact_id: str
    display_name: str
    size_bytes: int = Field(ge=0)
    mime_type: str
    sha256: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    captured_at: datetime | None = None
    gps: GPSInfo | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime


class ImageSummary(StrictSchema):
    image_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    gps_count: int = Field(ge=0)
    capture_span_seconds: int | None = Field(default=None, ge=0)


class ImageList(StrictSchema):
    items: list[ImageRead]
    next_cursor: str | None = None
    summary: ImageSummary


class DuplicateImage(StrictSchema):
    id: str
    display_name: str
    sha256: str


class RejectedImage(StrictSchema):
    display_name: str
    code: str
    detail: str


class ImageUploadResponse(StrictSchema):
    accepted: list[ImageRead]
    duplicates: list[DuplicateImage]
    rejected: list[RejectedImage]
    summary: ImageSummary

