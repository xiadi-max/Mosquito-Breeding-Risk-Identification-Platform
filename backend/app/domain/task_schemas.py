from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import ConfigDict, Field, model_validator

from app.domain.enums import TaskState, TaskType
from app.domain.schemas import StrictSchema


class TaskCreate(StrictSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    area: str = Field(min_length=1, max_length=200)
    survey_date: date
    task_type: TaskType


class TaskUpdate(StrictSchema):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    area: str | None = Field(default=None, min_length=1, max_length=200)
    survey_date: date | None = None
    task_type: TaskType | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "TaskUpdate":
        if not any(
            value is not None
            for value in (self.name, self.area, self.survey_date, self.task_type)
        ):
            raise ValueError("at least one task field must be provided")
        return self


class TaskRead(StrictSchema):
    id: str
    code: str
    name: str
    area: str
    survey_date: date
    task_type: TaskType
    state: TaskState
    progress: int = Field(ge=0, le=100)
    current_stage: str
    blocked_by: dict[str, Any] | None = None
    image_count: int = Field(ge=0)
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class TaskDetail(TaskRead):
    artifacts: dict[str, Any]
    links: dict[str, str]


class TaskList(StrictSchema):
    items: list[TaskRead]
    next_cursor: str | None = None

