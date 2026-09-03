from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.fingerprint import fingerprint
from app.core.time import utc_now
from app.domain.models import ROI, ROIVersion, Task
from app.domain.roi_schemas import ROICollection, ROIRead, ROIReplace, ROISource
from app.repositories.job_repository import JobRepository
from app.repositories.roi_repository import ROIRepository
from app.services.geometry_service import validate_polygon
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


class ROIService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = ROIRepository(session)

    def get(self, task_id: str) -> ROICollection:
        TaskService(self.session).get_model(task_id)
        current = self.repository.current(task_id)
        if current is None:
            return ROICollection(version=0, source=None, items=[])
        return self._collection(current)

    def replace(self, task_id: str, data: ROIReplace) -> ROICollection:
        task = TaskService(self.session).get_model(task_id)
        if JobRepository(self.session).active_for_task(task_id):
            raise AppError(
                status_code=409,
                code="JOB_ALREADY_RUNNING",
                title="任务仍有运行中的作业",
                detail="请先等待或取消当前作业，再修改 ROI。",
            )
        current = self.repository.current(task_id)
        current_version = current.version if current else 0
        if data.expected_version != current_version:
            raise AppError(
                status_code=409,
                code="VERSION_CONFLICT",
                title="资源版本冲突",
                detail=f"ROI 当前版本为 {current_version}，请刷新后重试。",
                errors=[{
                    "field": "expected_version",
                    "message": f"expected {data.expected_version}, current {current_version}",
                }],
            )
        mosaic = self.repository.current_mosaic(task_id)
        if mosaic is None or mosaic.id != data.source_artifact_id:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="拼接图不是当前有效版本",
                detail="ROI 必须绑定任务当前有效的高分辨率拼接图。",
            )
        if not mosaic.width or not mosaic.height:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="拼接图尺寸缺失",
                detail="当前拼接产物没有可用于 ROI 校验的原生尺寸。",
            )

        codes: set[str] = set()
        validated = []
        for item in data.items:
            if item.code in codes:
                raise AppError(
                    status_code=422,
                    code="VALIDATION_ERROR",
                    title="ROI 编号重复",
                    detail=f"同一版本中 ROI 编号 {item.code} 不能重复。",
                )
            codes.add(item.code)
            validated.append((item, validate_polygon(item.polygon, mosaic.width, mosaic.height)))

        normalized_snapshot = {
            "mosaic_artifact_id": mosaic.id,
            "source_width": mosaic.width,
            "source_height": mosaic.height,
            "coordinate_space": "mosaic_pixel",
            "items": [
                {
                    "code": item.code,
                    "visible": item.visible,
                    "polygon": polygon.points,
                }
                for item, polygon in validated
            ],
        }
        version = self.repository.next_version(task_id)
        now = utc_now()
        if current:
            current.is_current = False
        invalidated = WorkflowService(self.session).invalidate_from_roi(task_id)
        roi_version = ROIVersion(
            id=str(uuid4()),
            task_id=task_id,
            mosaic_artifact_id=mosaic.id,
            version=version,
            coordinate_space="mosaic_pixel",
            source_width=mosaic.width,
            source_height=mosaic.height,
            fingerprint=fingerprint(normalized_snapshot),
            is_current=True,
            created_at=now,
        )
        self.session.add(roi_version)
        for item, polygon in validated:
            self.session.add(
                ROI(
                    id=str(uuid4()),
                    roi_version=roi_version,
                    code=item.code,
                    visible=item.visible,
                    polygon_json=json.dumps(polygon.points, separators=(",", ":")),
                    area_px2=polygon.area_px2,
                    created_at=now,
                )
            )
        self.session.execute(
            update(Task)
            .where(Task.id == task.id)
            .values(version=Task.version + 1, updated_at=now)
        )
        self.session.commit()
        saved = self.repository.current(task_id)
        assert saved is not None
        return self._collection(saved, invalidated)

    def _collection(
        self, roi_version: ROIVersion, invalidated: list[str] | None = None
    ) -> ROICollection:
        return ROICollection(
            version=roi_version.version,
            coordinate_space="mosaic_pixel",
            source=ROISource(
                artifact_id=roi_version.mosaic_artifact_id,
                width=roi_version.source_width,
                height=roi_version.source_height,
            ),
            items=[
                ROIRead(
                    id=item.id,
                    code=item.code,
                    visible=item.visible,
                    polygon=json.loads(item.polygon_json),
                    area_px2=item.area_px2,
                    area_m2=item.area_m2,
                )
                for item in sorted(roi_version.rois, key=lambda value: value.code)
            ],
            invalidated=invalidated or [],
        )

