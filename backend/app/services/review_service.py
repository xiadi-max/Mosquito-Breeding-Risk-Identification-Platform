from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.core.errors import AppError
from app.core.pagination import decode_cursor, encode_cursor
from app.core.time import ensure_utc, utc_now
from app.domain.enums import DetectionState, ReviewActionType
from app.domain.inference_schemas import (
    BoxRead,
    CategoryRead,
    DetectionList,
    DetectionRead,
    PointRead,
    ReviewResult,
    ReviewUpdate,
)
from app.domain.models import Detection, GridTile, InferenceRun, ReviewAction, Task
from app.repositories.inference_repository import InferenceRepository
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


def detection_to_read(detection: Detection) -> DetectionRead:
    tile_box = json.loads(detection.tile_box_json)
    mosaic_box = json.loads(detection.mosaic_box_json)
    return DetectionRead(
        id=detection.id,
        code=detection.code,
        run_id=detection.inference_run_id,
        category=CategoryRead(id=detection.class_id, name=detection.class_name),
        confidence=detection.confidence,
        tile_box=BoxRead(**tile_box),
        mosaic_box=BoxRead(**mosaic_box),
        center=PointRead(x=detection.center_x, y=detection.center_y),
        source_grid=detection.source_grid_tile.code,
        auto_state=detection.auto_state,
        review_state=detection.effective_state,
        effective_state=detection.effective_state,
        version=detection.version,
        crop_artifact_id=detection.crop_artifact_id,
        created_at=ensure_utc(detection.created_at),
    )


class ReviewService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = InferenceRepository(session)

    def list_detections(
        self,
        task_id: str,
        *,
        run_id: str | None,
        status: str | None,
        category: str | None,
        min_confidence: float,
        limit: int,
        cursor: str | None,
    ) -> DetectionList:
        TaskService(self.session).get_model(task_id)
        run = self.repository.run(task_id, run_id) if run_id else self.repository.current_run(task_id)
        if run is None:
            return DetectionList(run_id=None, run_status=None, thresholds={}, stats={"total": 0, "accepted": 0, "pending": 0, "rejected": 0, "discarded": 0}, review_snapshot_version=0, items=[])
        statement = (
            select(Detection)
            .options(joinedload(Detection.source_grid_tile), joinedload(Detection.review_actions))
            .where(Detection.inference_run_id == run.id, Detection.confidence >= min_confidence)
        )
        if status:
            statement = statement.where(Detection.effective_state == status)
        if category:
            statement = statement.where(Detection.class_name == category)
        if cursor:
            created_at, entity_id = decode_cursor(cursor)
            created_at = created_at.replace(tzinfo=None)
            statement = statement.where(
                or_(Detection.created_at < created_at, (Detection.created_at == created_at) & (Detection.id < entity_id))
            )
        detections = list(self.session.execute(statement.order_by(Detection.created_at.desc(), Detection.id.desc()).limit(limit + 1)).unique().scalars())
        has_more = len(detections) > limit
        page = detections[:limit]
        next_cursor = encode_cursor(page[-1].created_at, page[-1].id) if has_more and page else None
        return DetectionList(
            run_id=run.id,
            run_status=run.status,
            thresholds=json.loads(run.thresholds_json),
            stats=self.repository.stats(run.id),
            review_snapshot_version=run.review_snapshot_version,
            items=[detection_to_read(item) for item in page],
            next_cursor=next_cursor,
        )

    def update(self, task_id: str, detection_id: str, data: ReviewUpdate) -> ReviewResult:
        TaskService(self.session).get_model(task_id)
        detection = self.repository.detection(task_id, detection_id)
        if detection is None:
            raise AppError(status_code=404, code="DETECTION_NOT_FOUND", title="检测结果不存在", detail="未找到指定检测结果。")
        if detection.inference_run.status != "current":
            raise AppError(status_code=400, code="INVALID_WORKFLOW_STATE", title="推理结果已失效", detail="不能复核已失效的推理结果。")
        previous = detection.effective_state
        if data.action == ReviewActionType.ACCEPT.value:
            new_state = DetectionState.ACCEPTED.value
        elif data.action == ReviewActionType.REJECT.value:
            new_state = DetectionState.REJECTED.value
        else:
            new_state = detection.auto_state
        result = self.session.execute(
            update(Detection)
            .where(Detection.id == detection_id, Detection.version == data.expected_version)
            .values(effective_state=new_state, version=Detection.version + 1)
        )
        if result.rowcount != 1:
            self.session.rollback()
            current = self.repository.detection(task_id, detection_id)
            current_version = current.version if current else "unknown"
            raise AppError(status_code=409, code="VERSION_CONFLICT", title="复核版本冲突", detail=f"检测结果当前版本为 {current_version}，请刷新后重试。")
        now = utc_now()
        self.session.add(ReviewAction(id=str(uuid4()), detection_id=detection_id, action=data.action,
            comment=data.comment, actor="operator", previous_effective_state=previous,
            new_effective_state=new_state, created_at=now))
        run = detection.inference_run
        run.review_snapshot_version += 1
        self.session.flush()
        stats = self.repository.stats(run.id)
        run.stats_json = json.dumps(stats, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        invalidated = WorkflowService(self.session).invalidate_from_review(task_id)
        self.session.execute(update(Task).where(Task.id == task_id).values(version=Task.version + 1, updated_at=now))
        self.session.commit()
        refreshed = self.repository.detection(task_id, detection_id)
        return ReviewResult(detection=detection_to_read(refreshed), stats=stats,
            review_snapshot_version=run.review_snapshot_version, invalidated=invalidated)
