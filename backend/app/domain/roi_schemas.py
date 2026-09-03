from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from app.domain.schemas import StrictSchema


Point = tuple[float, float]


class ROIInput(StrictSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str | None = None
    code: str = Field(min_length=1, max_length=40)
    visible: bool = True
    polygon: list[Point] = Field(min_length=3, max_length=10_000)

    @field_validator("polygon")
    @classmethod
    def finite_coordinates(cls, value: list[Point]) -> list[Point]:
        import math

        if any(not math.isfinite(coordinate) for point in value for coordinate in point):
            raise ValueError("polygon coordinates must be finite")
        return value


class ROIReplace(StrictSchema):
    expected_version: int = Field(ge=0)
    source_artifact_id: str
    coordinate_space: Literal["mosaic_pixel"] = "mosaic_pixel"
    items: list[ROIInput] = Field(max_length=100)


class ROIRead(StrictSchema):
    id: str
    code: str
    visible: bool
    polygon: list[Point]
    area_px2: float = Field(gt=0)
    area_m2: float | None = None


class ROISource(StrictSchema):
    artifact_id: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ROICollection(StrictSchema):
    version: int = Field(ge=0)
    coordinate_space: Literal["mosaic_pixel"] = "mosaic_pixel"
    source: ROISource | None
    items: list[ROIRead]
    invalidated: list[str] = Field(default_factory=list)

