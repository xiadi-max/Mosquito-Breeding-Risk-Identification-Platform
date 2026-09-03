from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveResponse(StrictSchema):
    status: Literal["ok"] = "ok"


class ReadyResponse(StrictSchema):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Any]


class ProviderSummary(StrictSchema):
    name: str
    configured: bool


class VersionResponse(StrictSchema):
    application: str
    version: str
    schema_revision: str | None
    commit: str | None
    environment: str
    providers: dict[str, ProviderSummary]
    limits: dict[str, int]


class ProblemItem(StrictSchema):
    field: str | None = None
    message: str


class ProblemDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[ProblemItem] = Field(default_factory=list)
    timestamp: datetime | None = None

