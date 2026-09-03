from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import ArtifactKind
from app.domain.models import Artifact, DecisionVersion, Detection, Export, GridPlan, Image, InferenceRun, ROI, ROIVersion, RiskRun, Task


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, task_id: str, *, include_deleting: bool = False) -> Task | None:
        statement = select(Task).where(Task.id == task_id, Task.deleted_at.is_(None))
        if not include_deleting:
            statement = statement.where(Task.state != "deleting")
        return self.session.execute(statement).scalar_one_or_none()

    def code_exists(self, code: str) -> bool:
        return self.session.execute(
            select(Task.id).where(Task.code == code)
        ).scalar_one_or_none() is not None

    def image_count(self, task_id: str) -> int:
        return int(
            self.session.execute(
                select(func.count(Image.id)).where(Image.task_id == task_id)
            ).scalar_one()
        )

    def has_current_mosaic(self, task_id: str) -> bool:
        return (
            self.session.execute(
                select(Artifact.id)
                .where(
                    Artifact.task_id == task_id,
                    Artifact.kind == ArtifactKind.MOSAIC.value,
                    Artifact.is_current.is_(True),
                    Artifact.deleted_at.is_(None),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def has_current_roi(self, task_id: str) -> bool:
        return (
            self.session.execute(
                select(ROI.id)
                .join(ROIVersion, ROI.roi_version_id == ROIVersion.id)
                .where(
                    ROIVersion.task_id == task_id,
                    ROIVersion.is_current.is_(True),
                )
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def has_current_grid(self, task_id: str) -> bool:
        return (
            self.session.execute(
                select(GridPlan.id)
                .where(GridPlan.task_id == task_id, GridPlan.status == "current")
                .limit(1)
            ).scalar_one_or_none()
            is not None
        )

    def current_inference_summary(self, task_id: str) -> tuple[bool, int]:
        run_id = self.session.execute(
            select(InferenceRun.id).where(
                InferenceRun.task_id == task_id, InferenceRun.status == "current"
            )
        ).scalar_one_or_none()
        if run_id is None:
            return False, 0
        pending = int(
            self.session.execute(
                select(func.count(Detection.id)).where(
                    Detection.inference_run_id == run_id,
                    Detection.effective_state == "pending",
                )
            ).scalar_one()
        )
        return True, pending

    def current_m5_summary(self, task_id: str) -> tuple[bool, bool, bool]:
        risk = self.session.execute(select(RiskRun.id).where(RiskRun.task_id==task_id,RiskRun.status=="current")).scalar_one_or_none() is not None
        decision = self.session.execute(select(DecisionVersion.id).where(DecisionVersion.task_id==task_id,DecisionVersion.status=="current")).scalar_one_or_none() is not None
        report = self.session.execute(select(Export.id).where(Export.task_id==task_id,Export.status=="ready",Export.format=="pdf")).scalar_one_or_none() is not None
        return risk, decision, report

    def list_page(
        self,
        *,
        q: str | None,
        state: str | None,
        limit: int,
        cursor: tuple[datetime, str] | None,
    ) -> list[tuple[Task, int, bool, bool, bool, bool, int, bool, bool, bool]]:
        image_count = (
            select(func.count(Image.id))
            .where(Image.task_id == Task.id)
            .correlate(Task)
            .scalar_subquery()
        )
        mosaic_count = (
            select(func.count(Artifact.id))
            .where(
                Artifact.task_id == Task.id,
                Artifact.kind == ArtifactKind.MOSAIC.value,
                Artifact.is_current.is_(True),
                Artifact.deleted_at.is_(None),
            )
            .correlate(Task)
            .scalar_subquery()
        )
        roi_count = (
            select(func.count(ROI.id))
            .join(ROIVersion, ROI.roi_version_id == ROIVersion.id)
            .where(ROIVersion.task_id == Task.id, ROIVersion.is_current.is_(True))
            .correlate(Task)
            .scalar_subquery()
        )
        grid_count = (
            select(func.count(GridPlan.id))
            .where(GridPlan.task_id == Task.id, GridPlan.status == "current")
            .correlate(Task)
            .scalar_subquery()
        )
        inference_count = (
            select(func.count(InferenceRun.id))
            .where(InferenceRun.task_id == Task.id, InferenceRun.status == "current")
            .correlate(Task)
            .scalar_subquery()
        )
        pending_count = (
            select(func.count(Detection.id))
            .join(InferenceRun, Detection.inference_run_id == InferenceRun.id)
            .where(
                InferenceRun.task_id == Task.id,
                InferenceRun.status == "current",
                Detection.effective_state == "pending",
            )
            .correlate(Task)
            .scalar_subquery()
        )
        risk_count = (select(func.count(RiskRun.id)).where(RiskRun.task_id==Task.id,RiskRun.status=="current").correlate(Task).scalar_subquery())
        decision_count = (select(func.count(DecisionVersion.id)).where(DecisionVersion.task_id==Task.id,DecisionVersion.status=="current").correlate(Task).scalar_subquery())
        report_count = (select(func.count(Export.id)).where(Export.task_id==Task.id,Export.status=="ready",Export.format=="pdf").correlate(Task).scalar_subquery())
        statement: Select = select(
            Task,
            image_count.label("image_count"),
            mosaic_count.label("mosaic_count"),
            roi_count.label("roi_count"),
            grid_count.label("grid_count"),
            inference_count.label("inference_count"),
            pending_count.label("pending_count"),
            risk_count.label("risk_count"),
            decision_count.label("decision_count"),
            report_count.label("report_count"),
        ).where(Task.deleted_at.is_(None), Task.state != "deleting")
        if q:
            escaped = q.strip()
            statement = statement.where(
                or_(
                    Task.name.contains(escaped, autoescape=True),
                    Task.code.contains(escaped, autoescape=True),
                    Task.task_type.contains(escaped, autoescape=True),
                    Task.area.contains(escaped, autoescape=True),
                )
            )
        if state:
            statement = statement.where(Task.state == state)
        if cursor:
            timestamp, entity_id = cursor
            timestamp = timestamp.replace(tzinfo=None)
            statement = statement.where(
                or_(
                    Task.updated_at < timestamp,
                    and_(Task.updated_at == timestamp, Task.id < entity_id),
                )
            )
        statement = statement.order_by(Task.updated_at.desc(), Task.id.desc()).limit(
            limit + 1
        )
        return [
            (row[0], int(row[1]), int(row[2]) > 0, int(row[3]) > 0, int(row[4]) > 0, int(row[5]) > 0, int(row[6]), int(row[7]) > 0, int(row[8]) > 0, int(row[9]) > 0)
            for row in self.session.execute(statement).all()
        ]

    def recent_tasks(self) -> list[tuple[Task, int, bool, bool, bool, bool, int, bool, bool, bool]]:
        image_count = (
            select(func.count(Image.id))
            .where(Image.task_id == Task.id)
            .correlate(Task)
            .scalar_subquery()
        )
        mosaic_count = (
            select(func.count(Artifact.id))
            .where(
                Artifact.task_id == Task.id,
                Artifact.kind == ArtifactKind.MOSAIC.value,
                Artifact.is_current.is_(True),
                Artifact.deleted_at.is_(None),
            )
            .correlate(Task)
            .scalar_subquery()
        )
        roi_count = (
            select(func.count(ROI.id))
            .join(ROIVersion, ROI.roi_version_id == ROIVersion.id)
            .where(ROIVersion.task_id == Task.id, ROIVersion.is_current.is_(True))
            .correlate(Task)
            .scalar_subquery()
        )
        grid_count = (
            select(func.count(GridPlan.id))
            .where(GridPlan.task_id == Task.id, GridPlan.status == "current")
            .correlate(Task)
            .scalar_subquery()
        )
        inference_count = (
            select(func.count(InferenceRun.id))
            .where(InferenceRun.task_id == Task.id, InferenceRun.status == "current")
            .correlate(Task)
            .scalar_subquery()
        )
        pending_count = (
            select(func.count(Detection.id))
            .join(InferenceRun, Detection.inference_run_id == InferenceRun.id)
            .where(InferenceRun.task_id == Task.id, InferenceRun.status == "current", Detection.effective_state == "pending")
            .correlate(Task)
            .scalar_subquery()
        )
        risk_count = (select(func.count(RiskRun.id)).where(RiskRun.task_id==Task.id,RiskRun.status=="current").correlate(Task).scalar_subquery())
        decision_count = (select(func.count(DecisionVersion.id)).where(DecisionVersion.task_id==Task.id,DecisionVersion.status=="current").correlate(Task).scalar_subquery())
        report_count = (select(func.count(Export.id)).where(Export.task_id==Task.id,Export.status=="ready",Export.format=="pdf").correlate(Task).scalar_subquery())
        statement = (
            select(
                Task,
                image_count.label("image_count"),
                mosaic_count.label("mosaic_count"),
                roi_count.label("roi_count"),
                grid_count.label("grid_count"),
                inference_count.label("inference_count"),
                pending_count.label("pending_count"),
                risk_count.label("risk_count"),
                decision_count.label("decision_count"),
                report_count.label("report_count"),
            )
            .where(Task.deleted_at.is_(None), Task.state != "deleting")
            .order_by(Task.updated_at.desc(), Task.id.desc())
        )
        return [
            (row[0], int(row[1]), int(row[2]) > 0, int(row[3]) > 0, int(row[4]) > 0, int(row[5]) > 0, int(row[6]), int(row[7]) > 0, int(row[8]) > 0, int(row[9]) > 0)
            for row in self.session.execute(statement).all()
        ]
