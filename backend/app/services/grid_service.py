from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import AppError
from app.core.fingerprint import canonical_json, fingerprint
from app.core.time import utc_now
from app.domain.enums import DerivedStatus, JobStatus, JobType, TaskState
from app.domain.grid_schemas import (
    GridParameters,
    GridPlanCreate,
    GridPlanRead,
    GridPreview,
    GridTileRead,
)
from app.domain.job_schemas import JobResource
from app.domain.models import GridPlan, GridTile, Job, JobEvent, Task
from app.repositories.grid_repository import GridRepository
from app.repositories.job_repository import JobRepository
from app.repositories.roi_repository import ROIRepository
from app.services.geometry_service import (
    GridTileSpec,
    build_grid,
    grid_fingerprint,
    validate_polygon,
)
from app.services.job_service import JobService, job_resource
from app.services.mosaic_service import JobCanceled, JobExecutionError
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


def _tile_read(tile: GridTileSpec) -> GridTileRead:
    return GridTileRead(
        code=tile.code,
        source_box=tile.source_box,
        padding=tile.padding,
        tile_to_mosaic=tile.tile_to_mosaic,
        roi_intersection=tile.roi_intersection,
    )


class GridService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.roi_repository = ROIRepository(session)
        self.grid_repository = GridRepository(session)

    def preview(self, task_id: str, data: GridParameters) -> GridPreview:
        TaskService(self.session).get_model(task_id)
        roi_version = self.roi_repository.by_version(task_id, data.roi_version)
        if roi_version is None or not roi_version.is_current:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="ROI 版本不是当前有效版本",
                detail="请使用当前 ROI 版本重新生成网格预览。",
            )
        mosaic = self.roi_repository.current_mosaic(task_id)
        if mosaic is None or mosaic.id != roi_version.mosaic_artifact_id:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="拼接图或 ROI 已失效",
                detail="当前 ROI 不再绑定有效拼接图，请重新保存 ROI。",
            )
        polygons = [
            validate_polygon(
                json.loads(item.polygon_json),
                roi_version.source_width,
                roi_version.source_height,
            ).geometry
            for item in roi_version.rois
            if item.visible
        ]
        tiles, step = build_grid(
            polygons,
            source_width=roi_version.source_width,
            source_height=roi_version.source_height,
            tile_size=data.tile_size,
            overlap=data.overlap,
            min_roi_intersection=data.min_roi_intersection,
        )
        if not tiles:
            raise AppError(
                status_code=400,
                code="GRID_EMPTY",
                title="网格结果为空",
                detail="当前 ROI 与相交阈值没有生成任何网格，请降低 min_roi_intersection。",
            )
        grid_hash = grid_fingerprint(
            roi_fingerprint=roi_version.fingerprint,
            mosaic_artifact_id=mosaic.id,
            tile_size=data.tile_size,
            overlap=data.overlap,
            step_px=step,
            min_roi_intersection=data.min_roi_intersection,
            tiles=tiles,
        )
        estimated = len(tiles) * data.tile_size * data.tile_size * 3
        return GridPreview(
            roi_version=roi_version.version,
            source_artifact_id=mosaic.id,
            tile_size=data.tile_size,
            overlap=data.overlap,
            step_px=step,
            edge_strategy=data.edge_strategy,
            min_roi_intersection=data.min_roi_intersection,
            count=len(tiles),
            padded_count=sum(1 for tile in tiles if any(tile.padding)),
            estimated_bytes=estimated,
            tiles=[_tile_read(tile) for tile in tiles],
            fingerprint=grid_hash,
        )

    def create_job(
        self,
        task_id: str,
        data: GridPlanCreate,
        idempotency_key: str | None,
    ) -> tuple[JobResource, bool]:
        task = TaskService(self.session).get_model(task_id)
        if task.state != TaskState.RUNNING.value:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="当前任务不能生成网格",
                detail="只有处理中的任务可以确认网格计划。",
            )
        preview = self.preview(
            task_id,
            GridParameters(**data.model_dump(exclude={"fingerprint"})),
        )
        if preview.fingerprint != data.fingerprint:
            raise AppError(
                status_code=409,
                code="GRID_PREVIEW_STALE",
                title="网格预览已失效",
                detail="ROI 或网格参数已变化，请重新预览后确认。",
            )
        input_snapshot = {
            "operation": JobType.GRID_GENERATE.value,
            "task_id": task_id,
            "roi_version": preview.roi_version,
            "source_artifact_id": preview.source_artifact_id,
            "tile_size": preview.tile_size,
            "overlap": preview.overlap,
            "edge_strategy": preview.edge_strategy,
            "min_roi_intersection": preview.min_roi_intersection,
            "preview_fingerprint": preview.fingerprint,
        }
        request_hash = fingerprint(input_snapshot)
        effective_key = (idempotency_key or f"auto:{preview.fingerprint}").strip()
        if not effective_key or len(effective_key) > 255:
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                title="幂等键无效",
                detail="Idempotency-Key 长度必须为 1–255 个字符。",
            )
        jobs = JobRepository(self.session)
        existing = jobs.get_idempotent(task_id, JobType.GRID_GENERATE.value, effective_key)
        if existing:
            if existing.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    title="幂等键已用于不同请求",
                    detail="请为不同网格参数使用新的 Idempotency-Key。",
                )
            return job_resource(existing), False
        active = jobs.active_for_type(task_id, JobType.GRID_GENERATE.value)
        if active:
            raise AppError(
                status_code=409,
                code="JOB_ALREADY_RUNNING",
                title="网格作业正在执行",
                detail=f"任务已有未结束的网格作业 {active.id}。",
            )
        now = utc_now()
        job = Job(
            id=str(uuid4()),
            task_id=task_id,
            type=JobType.GRID_GENERATE.value,
            status=JobStatus.QUEUED.value,
            progress=0,
            current_step="queued",
            message="网格生成作业已进入队列",
            input_json=canonical_json(input_snapshot),
            input_fingerprint=preview.fingerprint,
            idempotency_key=effective_key,
            request_hash=request_hash,
            available_at=now,
            attempt_count=0,
            max_attempts=self.settings.job_max_retries,
            created_at=now,
        )
        self.session.add(job)
        try:
            self.session.flush()
        except IntegrityError:
            # A concurrent request may have inserted the same idempotency key.
            self.session.rollback()
            concurrent = jobs.get_idempotent(
                task_id, JobType.GRID_GENERATE.value, effective_key
            )
            if concurrent is None:
                raise
            if concurrent.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    title="幂等键已用于不同请求",
                    detail="请为不同网格参数使用新的 Idempotency-Key。",
                )
            return job_resource(concurrent), False
        self.session.add(
            JobEvent(
                job_id=job.id,
                event_type="job.queued",
                data_json=canonical_json(
                    {"job_id": job.id, "status": job.status, "message": job.message}
                ),
                created_at=now,
            )
        )
        self.session.commit()
        return job_resource(job), True

    def get_current(self, task_id: str) -> GridPlanRead:
        TaskService(self.session).get_model(task_id)
        plan = self.grid_repository.current(task_id)
        if plan is None:
            raise AppError(
                status_code=404,
                code="GRID_PLAN_NOT_FOUND",
                title="网格计划不存在",
                detail="任务尚无当前有效网格计划。",
            )
        return self._plan_read(plan)

    @staticmethod
    def _plan_read(plan: GridPlan) -> GridPlanRead:
        return GridPlanRead(
            id=plan.id,
            task_id=plan.task_id,
            roi_version=plan.roi_version.version,
            source_artifact_id=plan.mosaic_artifact_id,
            status=plan.status,
            tile_size=plan.tile_size,
            overlap=plan.overlap,
            step_px=plan.step_px,
            edge_strategy=plan.edge_strategy,
            min_roi_intersection=plan.min_roi_intersection,
            count=plan.tile_count,
            padded_count=plan.padded_count,
            estimated_bytes=plan.estimated_bytes,
            fingerprint=plan.fingerprint,
            tiles=[
                GridTileRead(
                    code=tile.code,
                    source_box=(tile.source_x1, tile.source_y1, tile.source_x2, tile.source_y2),
                    padding=(tile.pad_left, tile.pad_top, tile.pad_right, tile.pad_bottom),
                    tile_to_mosaic=json.loads(tile.tile_to_mosaic_json),
                    roi_intersection=tile.roi_intersection,
                )
                for tile in sorted(plan.tiles, key=lambda value: value.code)
            ],
        )


class GridJobExecutor:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings

    def execute(self, job_id: str, worker_id: str) -> dict[str, Any]:
        with self.factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.worker_id != worker_id or job.status != JobStatus.RUNNING.value:
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 已失去网格作业租约。")
            snapshot = json.loads(job.input_json)
            task_id = job.task_id

        self._progress(job_id, worker_id, 10, "validate_roi", "正在校验 ROI 与拼接图版本")
        with self.factory() as session:
            service = GridService(session, self.settings)
            preview = service.preview(
                task_id,
                GridParameters(
                    roi_version=snapshot["roi_version"],
                    tile_size=snapshot["tile_size"],
                    overlap=snapshot["overlap"],
                    edge_strategy=snapshot["edge_strategy"],
                    min_roi_intersection=snapshot["min_roi_intersection"],
                ),
            )
        if preview.fingerprint != snapshot["preview_fingerprint"]:
            raise JobExecutionError(
                "GRID_INPUT_STALE", "ROI 或拼接图在作业执行前已变化，请重新预览。"
            )
        self._progress(job_id, worker_id, 45, "enumerate", "已枚举 ROI 相交网格")
        self._progress(job_id, worker_id, 75, "metadata", "正在生成补边与坐标变换元数据")
        with self.factory() as session:
            current_job = session.get(Job, job_id)
            if current_job is None or current_job.worker_id != worker_id:
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 已失去网格作业租约。")
            if current_job.cancel_requested_at:
                raise JobCanceled
            roi_version = ROIRepository(session).by_version(task_id, preview.roi_version)
            if roi_version is None or not roi_version.is_current:
                raise JobExecutionError("GRID_INPUT_STALE", "ROI 已失效，请重新生成网格。")
            session.execute(
                update(GridPlan)
                .where(GridPlan.task_id == task_id, GridPlan.status == DerivedStatus.CURRENT.value)
                .values(status=DerivedStatus.STALE.value)
            )
            plan = GridPlan(
                id=str(uuid4()),
                task_id=task_id,
                roi_version_id=roi_version.id,
                mosaic_artifact_id=preview.source_artifact_id,
                job_id=job_id,
                tile_size=preview.tile_size,
                overlap=preview.overlap,
                step_px=preview.step_px,
                edge_strategy=preview.edge_strategy,
                min_roi_intersection=preview.min_roi_intersection,
                tile_count=preview.count,
                padded_count=preview.padded_count,
                estimated_bytes=preview.estimated_bytes,
                fingerprint=preview.fingerprint,
                status=DerivedStatus.CURRENT.value,
                created_at=utc_now(),
            )
            session.add(plan)
            for tile in preview.tiles:
                session.add(
                    GridTile(
                        id=str(uuid4()),
                        grid_plan=plan,
                        code=tile.code,
                        source_x1=tile.source_box[0],
                        source_y1=tile.source_box[1],
                        source_x2=tile.source_box[2],
                        source_y2=tile.source_box[3],
                        pad_left=tile.padding[0],
                        pad_top=tile.padding[1],
                        pad_right=tile.padding[2],
                        pad_bottom=tile.padding[3],
                        tile_to_mosaic_json=canonical_json(tile.tile_to_mosaic),
                        roi_intersection=tile.roi_intersection,
                    )
                )
            WorkflowService(session).invalidate_from_grid(task_id)
            session.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(version=Task.version + 1, updated_at=utc_now())
            )
            session.flush()
            result = {
                "grid_plan_id": plan.id,
                "tile_count": plan.tile_count,
                "padded_count": plan.padded_count,
                "fingerprint": plan.fingerprint,
            }
            JobService(session, self.settings).succeed(job_id, worker_id, result)
            return result

    def _progress(self, job_id: str, worker_id: str, progress: int, step: str, message: str) -> None:
        with self.factory() as session:
            service = JobService(session, self.settings)
            if service.cancellation_requested(job_id):
                raise JobCanceled
            service.report_progress(
                job_id, worker_id, progress=progress, step=step, message=message
            )
