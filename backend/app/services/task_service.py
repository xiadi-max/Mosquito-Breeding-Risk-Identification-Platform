from __future__ import annotations

import shutil
from datetime import datetime
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import resolve_storage_path
from app.core.time import ensure_utc, utc_now
from app.domain.enums import TaskState
from app.domain.models import Task
from app.domain.task_schemas import TaskCreate, TaskDetail, TaskList, TaskRead, TaskUpdate
from app.repositories.task_repository import TaskRepository
from app.repositories.job_repository import JobRepository


def parse_expected_version(if_match: str | None, body_version: int | None) -> int:
    header_version: int | None = None
    if if_match:
        value = if_match.strip()
        if value.startswith("W/"):
            value = value[2:]
        value = value.strip('"')
        try:
            header_version = int(value)
        except ValueError as exc:
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                title="版本参数无效",
                detail="If-Match 必须包含整数版本号。",
                errors=[{"field": "If-Match", "message": "invalid version"}],
            ) from exc
    if header_version is not None and body_version is not None and header_version != body_version:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            title="版本参数不一致",
            detail="If-Match 与 expected_version 必须一致。",
        )
    version = header_version if header_version is not None else body_version
    if version is None or version < 1:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            title="缺少资源版本",
            detail="修改任务时必须提供 If-Match 或 expected_version。",
            errors=[{"field": "expected_version", "message": "field required"}],
        )
    return version


def task_progress(
    image_count: int,
    has_current_mosaic: bool = False,
    has_current_roi: bool = False,
    has_current_grid: bool = False,
    has_current_inference: bool = False,
    pending_review_count: int = 0,
    has_current_risk: bool = False,
    has_current_decision: bool = False,
    has_ready_report: bool = False,
) -> tuple[int, str, dict | None]:
    if has_current_decision or has_ready_report:
        return 100, "completed", None
    if has_current_risk and pending_review_count == 0:
        return 85, "risk", None
    if has_current_inference:
        blocked = (
            {"code": "PENDING_REVIEWS", "count": pending_review_count}
            if pending_review_count > 0
            else None
        )
        return 71, "inference", blocked
    if has_current_grid:
        return 57, "grid", None
    if has_current_roi:
        return 42, "roi", None
    if has_current_mosaic:
        return 28, "mosaic", None
    if image_count > 0:
        return 14, "image_ingest", None
    return 0, "task_created", None


def task_to_read(
    task: Task,
    image_count: int,
    has_current_mosaic: bool = False,
    has_current_roi: bool = False,
    has_current_grid: bool = False,
    has_current_inference: bool = False,
    pending_review_count: int = 0,
    has_current_risk: bool = False,
    has_current_decision: bool = False,
    has_ready_report: bool = False,
) -> TaskRead:
    progress, stage, blocked_by = task_progress(
        image_count,
        has_current_mosaic,
        has_current_roi,
        has_current_grid,
        has_current_inference,
        pending_review_count,
        has_current_risk,
        has_current_decision,
        has_ready_report,
    )
    return TaskRead(
        id=task.id,
        code=task.code,
        name=task.name,
        area=task.area,
        survey_date=task.survey_date,
        task_type=task.task_type,
        state=task.state,
        progress=progress,
        current_stage=stage,
        blocked_by=blocked_by,
        image_count=image_count,
        version=task.version,
        created_at=ensure_utc(task.created_at),
        updated_at=ensure_utc(task.updated_at),
        archived_at=ensure_utc(task.archived_at) if task.archived_at else None,
    )


class TaskService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = TaskRepository(session)

    def create(self, data: TaskCreate) -> TaskDetail:
        code_prefix = data.survey_date.strftime("T-%Y%m%d-")
        code = ""
        for _ in range(20):
            candidate = code_prefix + uuid4().hex[:4].upper()
            if not self.repository.code_exists(candidate):
                code = candidate
                break
        if not code:
            raise AppError(
                status_code=500,
                code="TASK_CODE_GENERATION_FAILED",
                title="任务编号生成失败",
                detail="暂时无法生成唯一任务编号，请重试。",
            )
        now = utc_now()
        task = Task(
            id=str(uuid4()),
            code=code,
            name=data.name,
            area=data.area,
            survey_date=data.survey_date,
            task_type=data.task_type.value,
            state=TaskState.RUNNING.value,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(task)
        self.session.commit()
        self.session.refresh(task)
        return self._detail(task, 0)

    def get_model(self, task_id: str, *, include_deleting: bool = False) -> Task:
        task = self.repository.get(task_id, include_deleting=include_deleting)
        if task is None:
            raise AppError(
                status_code=404,
                code="TASK_NOT_FOUND",
                title="任务不存在",
                detail="未找到指定任务。",
            )
        return task

    def get(self, task_id: str) -> TaskDetail:
        task = self.get_model(task_id)
        has_inference, pending = self.repository.current_inference_summary(task.id)
        has_risk, has_decision, has_report = self.repository.current_m5_summary(task.id)
        return self._detail(
            task,
            self.repository.image_count(task.id),
            self.repository.has_current_mosaic(task.id),
            self.repository.has_current_roi(task.id),
            self.repository.has_current_grid(task.id),
            has_inference,
            pending,
            has_risk,
            has_decision,
            has_report,
        )

    def list(
        self,
        *,
        q: str | None,
        state: str | None,
        limit: int,
        cursor: str | None,
    ) -> TaskList:
        decoded = decode_cursor(cursor) if cursor else None
        rows = self.repository.list_page(
            q=q, state=state, limit=limit, cursor=decoded
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = None
        if has_more and page:
            next_cursor = encode_cursor(page[-1][0].updated_at, page[-1][0].id)
        return TaskList(
            items=[
                task_to_read(
                    task,
                    count,
                    has_mosaic,
                    has_roi,
                    has_grid,
                    has_inference,
                    pending,
                    has_risk,
                    has_decision,
                    has_report,
                )
                for task, count, has_mosaic, has_roi, has_grid, has_inference, pending, has_risk, has_decision, has_report in page
            ],
            next_cursor=next_cursor,
        )

    def update(
        self, task_id: str, data: TaskUpdate, expected_version: int
    ) -> TaskDetail:
        values = data.model_dump(exclude_none=True, exclude={"expected_version"})
        if "task_type" in values:
            values["task_type"] = values["task_type"].value
        values["version"] = expected_version + 1
        values["updated_at"] = utc_now()
        result = self.session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.deleted_at.is_(None),
                Task.state != TaskState.DELETING.value,
                Task.version == expected_version,
            )
            .values(**values)
        )
        if result.rowcount != 1:
            self.session.rollback()
            current = self.repository.get(task_id)
            if current is None:
                self.get_model(task_id)
            raise AppError(
                status_code=409,
                code="VERSION_CONFLICT",
                title="资源版本冲突",
                detail=f"任务当前版本为 {current.version}，请刷新后重试。",
                errors=[
                    {
                        "field": "expected_version",
                        "message": f"expected {expected_version}, current {current.version}",
                    }
                ],
            )
        self.session.commit()
        return self.get(task_id)

    def archive(self, task_id: str, expected_version: int) -> TaskDetail:
        task = self.get_model(task_id)
        self._reject_active_job(task_id)
        if task.version != expected_version:
            raise AppError(
                status_code=409,
                code="VERSION_CONFLICT",
                title="资源版本冲突",
                detail=f"任务当前版本为 {task.version}，请刷新后重试。",
                errors=[
                    {
                        "field": "expected_version",
                        "message": f"expected {expected_version}, current {task.version}",
                    }
                ],
            )
        if task.state == TaskState.ARCHIVED.value:
            return self._detail(
                task,
                self.repository.image_count(task.id),
                self.repository.has_current_mosaic(task.id),
                self.repository.has_current_roi(task.id),
                self.repository.has_current_grid(task.id),
            )
        if task.state != TaskState.RUNNING.value and task.state != TaskState.DONE.value:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="当前状态不能归档",
                detail=f"状态 {task.state} 的任务不能归档。",
            )
        now = utc_now()
        result = self.session.execute(
            update(Task)
            .where(
                Task.id == task_id,
                Task.version == expected_version,
                Task.state.in_(
                    [TaskState.RUNNING.value, TaskState.DONE.value]
                ),
            )
            .values(
                state=TaskState.ARCHIVED.value,
                archived_at=now,
                updated_at=now,
                version=expected_version + 1,
            )
        )
        if result.rowcount != 1:
            self.session.rollback()
            current = self.get_model(task_id)
            raise AppError(
                status_code=409,
                code="VERSION_CONFLICT",
                title="资源版本冲突",
                detail=f"任务当前版本为 {current.version}，请刷新后重试。",
            )
        self.session.commit()
        return self.get(task_id)

    def delete(self, task_id: str, storage_root) -> None:
        task = self.get_model(task_id)
        self._reject_active_job(task_id)
        task.state = TaskState.DELETING.value
        task.updated_at = utc_now()
        task.version += 1
        self.session.commit()

        task_directory = resolve_storage_path(storage_root, f"tasks/{task.id}")
        try:
            if task_directory.exists():
                shutil.rmtree(task_directory)
        except OSError as exc:
            raise AppError(
                status_code=500,
                code="TASK_DELETE_FAILED",
                title="任务文件删除失败",
                detail="任务已标记为删除中，可在处理文件占用后重试。",
            ) from exc

        self.session.delete(task)
        self.session.commit()

    def _detail(
        self,
        task: Task,
        image_count: int,
        has_current_mosaic: bool = False,
        has_current_roi: bool = False,
        has_current_grid: bool = False,
        has_current_inference: bool = False,
        pending_review_count: int = 0,
        has_current_risk: bool = False,
        has_current_decision: bool = False,
        has_ready_report: bool = False,
    ) -> TaskDetail:
        base = task_to_read(
            task,
            image_count,
            has_current_mosaic,
            has_current_roi,
            has_current_grid,
            has_current_inference,
            pending_review_count,
            has_current_risk,
            has_current_decision,
            has_ready_report,
        )
        return TaskDetail(
            **base.model_dump(),
            artifacts={"original_image_count": image_count},
            links={
                "self": f"/api/v1/tasks/{task.id}",
                "images": f"/api/v1/tasks/{task.id}/images",
            },
        )

    def _reject_active_job(self, task_id: str) -> None:
        active = JobRepository(self.session).active_for_task(task_id)
        if active:
            raise AppError(
                status_code=409,
                code="JOB_ALREADY_RUNNING",
                title="任务仍有运行中的作业",
                detail=f"请先等待或取消作业 {active.id}。",
            )
