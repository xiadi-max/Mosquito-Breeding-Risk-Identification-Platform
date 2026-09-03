from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.models import Detection, InferenceRun, ModelVersion


class InferenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def current_run(self, task_id: str) -> InferenceRun | None:
        return self.session.execute(
            select(InferenceRun)
            .options(joinedload(InferenceRun.model_version))
            .where(InferenceRun.task_id == task_id, InferenceRun.status == "current")
        ).unique().scalar_one_or_none()

    def run(self, task_id: str, run_id: str) -> InferenceRun | None:
        return self.session.execute(
            select(InferenceRun).where(
                InferenceRun.task_id == task_id, InferenceRun.id == run_id
            )
        ).scalar_one_or_none()

    def model(self, model_id: str) -> ModelVersion | None:
        return self.session.get(ModelVersion, model_id)

    def active_model(self, provider: str) -> ModelVersion | None:
        return self.session.execute(
            select(ModelVersion).where(
                ModelVersion.provider == provider, ModelVersion.active.is_(True)
            )
        ).scalar_one_or_none()

    def detection(self, task_id: str, detection_id: str) -> Detection | None:
        return self.session.execute(
            select(Detection)
            .options(
                joinedload(Detection.inference_run),
                joinedload(Detection.source_grid_tile),
                selectinload(Detection.review_actions),
            )
            .join(InferenceRun, Detection.inference_run_id == InferenceRun.id)
            .where(InferenceRun.task_id == task_id, Detection.id == detection_id)
        ).scalar_one_or_none()

    def stats(self, run_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(Detection.effective_state, func.count(Detection.id))
            .where(Detection.inference_run_id == run_id)
            .group_by(Detection.effective_state)
        ).all()
        result = {"total": 0, "accepted": 0, "pending": 0, "rejected": 0, "discarded": 0}
        for state, count in rows:
            result[state] = int(count)
            result["total"] += int(count)
        return result
