from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.models import GridPlan


class GridRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def current(self, task_id: str) -> GridPlan | None:
        return self.session.execute(
            select(GridPlan)
            .options(
                selectinload(GridPlan.tiles),
                joinedload(GridPlan.roi_version),
            )
            .where(GridPlan.task_id == task_id, GridPlan.status == "current")
        ).scalar_one_or_none()

    def get(self, plan_id: str) -> GridPlan | None:
        return self.session.execute(
            select(GridPlan)
            .options(
                selectinload(GridPlan.tiles),
                joinedload(GridPlan.roi_version),
            )
            .where(GridPlan.id == plan_id)
        ).scalar_one_or_none()

    def by_job(self, job_id: str) -> GridPlan | None:
        return self.session.execute(
            select(GridPlan)
            .options(selectinload(GridPlan.tiles))
            .where(GridPlan.job_id == job_id)
        ).scalar_one_or_none()

