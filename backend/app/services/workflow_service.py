from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.domain.enums import ArtifactKind
from app.domain.models import Artifact, DecisionVersion, Export, GridPlan, InferenceRun, RiskRun, ROIVersion


class WorkflowService:
    """Centralizes M3 invalidation; later milestones extend this dependency graph."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def invalidate_from_images(self, task_id: str) -> list[str]:
        self.session.execute(
            update(ROIVersion)
            .where(ROIVersion.task_id == task_id, ROIVersion.is_current.is_(True))
            .values(is_current=False)
        )
        self._invalidate_inference(task_id)
        self.session.execute(
            update(GridPlan)
            .where(GridPlan.task_id == task_id, GridPlan.status == "current")
            .values(status="stale")
        )
        return ["mosaic", "roi", "grid_plan", "inference_run", "risk_run", "decision", "exports"]

    def invalidate_from_mosaic(self, task_id: str) -> list[str]:
        self.session.execute(
            update(ROIVersion)
            .where(ROIVersion.task_id == task_id, ROIVersion.is_current.is_(True))
            .values(is_current=False)
        )
        self._invalidate_inference(task_id)
        self.session.execute(
            update(GridPlan)
            .where(GridPlan.task_id == task_id, GridPlan.status == "current")
            .values(status="stale")
        )
        return ["roi", "grid_plan", "inference_run", "risk_run", "decision", "exports"]

    def invalidate_from_roi(self, task_id: str) -> list[str]:
        self.session.execute(
            update(GridPlan)
            .where(GridPlan.task_id == task_id, GridPlan.status == "current")
            .values(status="stale")
        )
        self._invalidate_inference(task_id)
        return ["grid_plan", "inference_run", "risk_run", "decision", "exports"]

    def invalidate_from_grid(self, task_id: str) -> list[str]:
        self._invalidate_inference(task_id)
        return ["inference_run", "risk_run", "decision", "exports"]

    def invalidate_from_inference(self, task_id: str) -> list[str]:
        self._invalidate_risk(task_id)
        return ["risk_run", "decision", "exports"]

    def invalidate_from_review(self, task_id: str) -> list[str]:
        self._invalidate_risk(task_id)
        return ["risk_run", "decision", "exports"]

    def invalidate_from_risk(self, task_id: str) -> list[str]:
        self.session.execute(update(DecisionVersion).where(DecisionVersion.task_id == task_id, DecisionVersion.status == "current").values(status="stale"))
        self.session.execute(update(Export).where(Export.task_id == task_id, Export.status == "ready").values(status="stale"))
        return ["decision", "exports"]

    def invalidate_from_decision(self, task_id: str, decision_version_id: str | None = None) -> list[str]:
        statement = update(Export).where(Export.task_id == task_id, Export.status == "ready")
        if decision_version_id is not None:
            statement = statement.where(Export.decision_version_id == decision_version_id)
        self.session.execute(statement.values(status="stale"))
        return ["exports"]

    def _invalidate_inference(self, task_id: str) -> None:
        self.session.execute(
            update(InferenceRun)
            .where(InferenceRun.task_id == task_id, InferenceRun.status == "current")
            .values(status="stale")
        )
        self.session.execute(
            update(Artifact)
            .where(
                Artifact.task_id == task_id,
                Artifact.kind.in_(
                    [
                        ArtifactKind.PREDICTIONS_JSON.value,
                        ArtifactKind.REVIEW_CROP.value,
                    ]
                ),
                Artifact.is_current.is_(True),
            )
            .values(is_current=False)
        )
        self._invalidate_risk(task_id)

    def _invalidate_risk(self, task_id: str) -> None:
        self.session.execute(update(RiskRun).where(RiskRun.task_id == task_id, RiskRun.status == "current").values(status="stale"))
        self.session.execute(update(Artifact).where(Artifact.task_id == task_id, Artifact.kind == ArtifactKind.DENSITY_PREVIEW.value, Artifact.is_current.is_(True)).values(is_current=False))
        self.session.execute(update(DecisionVersion).where(DecisionVersion.task_id == task_id, DecisionVersion.status == "current").values(status="stale"))
        self.session.execute(update(Export).where(Export.task_id == task_id, Export.status == "ready").values(status="stale"))
