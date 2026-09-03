from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.domain.enums import JobStatus, JobType
from app.domain.schemas import StrictSchema


class MosaicOptions(StrictSchema):
    """Reserved for versioned, server-approved options; SCANS settings are environment-only."""

    pass


class MosaicJobCreate(StrictSchema):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["auto", "fake", "opencv"] = "auto"
    options: MosaicOptions = Field(default_factory=MosaicOptions)


class JobRead(StrictSchema):
    id: str
    task_id: str
    type: JobType
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    current_step: str
    message: str | None = None
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    cancel_requested_at: datetime | None = None
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobLinks(StrictSchema):
    self: str
    events: str
    cancel: str


class JobResource(StrictSchema):
    job: JobRead
    links: JobLinks
