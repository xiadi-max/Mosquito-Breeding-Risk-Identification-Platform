from __future__ import annotations

import html
import json

from sqlalchemy.orm import Session

from app import __version__
from app.core.config import Settings
from app.core.errors import AppError
from app.domain.dashboard_schemas import DashboardMeta, DashboardResponse
from app.domain.enums import TaskState
from app.repositories.image_repository import ImageRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.roi_repository import ROIRepository
from app.repositories.inference_repository import InferenceRepository
from app.services.review_service import detection_to_read
from app.services.geometry_service import native_to_svg
from app.services.task_service import task_progress


STATUS_LABELS = {
    TaskState.RUNNING.value: "处理中",
    TaskState.DONE.value: "已完成",
    TaskState.ARCHIVED.value: "已归档",
}


class DashboardService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.task_repository = TaskRepository(session)
        self.image_repository = ImageRepository(session)

    def get(self, task_id: str | None) -> DashboardResponse:
        rows = self.task_repository.recent_tasks()
        selected = None
        if task_id:
            selected = next((row for row in rows if row[0].id == task_id), None)
            if selected is None:
                raise AppError(
                    status_code=404,
                    code="TASK_NOT_FOUND",
                    title="任务不存在",
                    detail="未找到指定任务。",
                )
        elif rows:
            selected = next(
                (row for row in rows if row[0].state == TaskState.RUNNING.value),
                rows[0],
            )

        current_id = selected[0].id if selected else None
        task_items = []
        for task, image_count, has_mosaic, has_roi, has_grid, has_inference, pending, has_risk, has_decision, has_report in rows:
            progress, _, _ = task_progress(
                image_count,
                has_mosaic,
                has_roi,
                has_grid,
                has_inference,
                pending,
                has_risk,
                has_decision,
                has_report,
            )
            task_items.append(
                {
                    "uuid": task.id,
                    "name": task.name,
                    "id": task.code,
                    "type": task.task_type,
                    "status": STATUS_LABELS.get(task.state, task.state),
                    "state": task.state,
                    "progress": progress,
                    "date": task.survey_date.isoformat(),
                    "summary": f"{image_count} 张影像",
                    "selected": task.id == current_id,
                }
            )

        demo_images = []
        if current_id:
            for image in self.image_repository.list_for_task(current_id):
                demo_images.append(
                    {
                        "id": image.id,
                        "artifact_id": image.artifact_id,
                        "name": html.escape(image.display_name),
                        "size": image.size_bytes,
                        "mime_type": image.mime_type,
                    }
                )

        legacy_rois = []
        if current_id:
            roi_version = ROIRepository(self.session).current(current_id)
            if roi_version:
                for item in sorted(roi_version.rois, key=lambda value: value.code):
                    points = [
                        native_to_svg(
                            x,
                            y,
                            viewbox_width=900,
                            viewbox_height=545,
                            source_width=roi_version.source_width,
                            source_height=roi_version.source_height,
                        )
                        for x, y in json.loads(item.polygon_json)
                    ]
                    legacy_rois.append(
                        {"id": item.code, "visible": item.visible, "points": points}
                    )

        completed_target_count = 0
        legacy_reviews = []
        model_version = InferenceRepository(self.session).active_model(
            self.settings.detector_provider
        )
        if current_id:
            run = InferenceRepository(self.session).current_run(current_id)
            if run:
                model_version = run.model_version
                from sqlalchemy import select
                from sqlalchemy.orm import joinedload
                from app.domain.models import Detection

                detections = list(
                    self.session.execute(
                        select(Detection)
                        .options(
                            joinedload(Detection.source_grid_tile),
                            joinedload(Detection.review_actions),
                        )
                        .where(Detection.inference_run_id == run.id)
                    ).unique().scalars()
                )
                completed_target_count = sum(
                    item.effective_state == "accepted" for item in detections
                )
                for item in detections:
                    if item.effective_state != "pending":
                        continue
                    read = detection_to_read(item)
                    legacy_reviews.append(
                        {
                            "id": read.code,
                            "detection_id": read.id,
                            "category": read.category.name,
                            "confidence": read.confidence,
                            "grid": read.source_grid,
                            "crop_artifact_id": read.crop_artifact_id,
                            "version": read.version,
                        }
                    )

        legacy_hotspots = []
        if current_id:
            from app.repositories.m5_repository import M5Repository

            risk_run = M5Repository(self.session).current_risk(current_id)
            if risk_run:
                for hotspot in risk_run.hotspots:
                    legacy_hotspots.append(
                        {
                            "id": hotspot.code,
                            "name": hotspot.name,
                            "clusteringIndex": hotspot.clustering_index,
                            "clusteringLevel": hotspot.clustering_level,
                            "targetCount": hotspot.target_count,
                            "contour": __import__("json").loads(hotspot.polygon_pixel_json),
                            "centroid": [hotspot.centroid_x, hotspot.centroid_y],
                        }
                    )

        return DashboardResponse(
            meta=DashboardMeta(
                api_version="v1",
                current_task_id=current_id,
                capabilities={
                    "mosaic": self.settings.mosaic_provider,
                    "detector": self.settings.detector_provider,
                    "decision": self.settings.decision_provider,
                    "backend": __version__,
                },
            ),
            tasks=task_items,
            demoImages=demo_images,
            rois=legacy_rois,
            model={
                "completedTargetCount": completed_target_count,
                "reviews": legacy_reviews,
                "provider": self.settings.detector_provider,
                "activeVersion": (
                    {
                        "id": model_version.id,
                        "name": model_version.name,
                        "provider": model_version.provider,
                        "weightsLabel": model_version.weights_label,
                        "inputSize": model_version.input_size,
                        "device": model_version.device,
                        "codeVersion": model_version.code_version,
                        "classCount": len(json.loads(model_version.class_map_json)),
                    }
                    if model_version
                    else None
                ),
            },
            risk={
                "highThreshold": self.settings.risk_high_threshold,
                "mediumThreshold": self.settings.risk_medium_threshold,
                "hotspots": legacy_hotspots,
            },
        )
