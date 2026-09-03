from __future__ import annotations

from typing import Any

from app.domain.schemas import StrictSchema


class DashboardMeta(StrictSchema):
    api_version: str
    current_task_id: str | None
    capabilities: dict[str, str]


class DashboardResponse(StrictSchema):
    meta: DashboardMeta
    tasks: list[dict[str, Any]]
    demoImages: list[dict[str, Any]]
    rois: list[dict[str, Any]]
    model: dict[str, Any]
    risk: dict[str, Any]

