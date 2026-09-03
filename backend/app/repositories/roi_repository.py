from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.domain.models import Artifact, ROIVersion


class ROIRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def current(self, task_id: str) -> ROIVersion | None:
        return self.session.execute(
            select(ROIVersion)
            .options(selectinload(ROIVersion.rois))
            .where(ROIVersion.task_id == task_id, ROIVersion.is_current.is_(True))
        ).scalar_one_or_none()

    def by_version(self, task_id: str, version: int) -> ROIVersion | None:
        return self.session.execute(
            select(ROIVersion)
            .options(selectinload(ROIVersion.rois))
            .where(ROIVersion.task_id == task_id, ROIVersion.version == version)
        ).scalar_one_or_none()

    def next_version(self, task_id: str) -> int:
        current = self.session.execute(
            select(func.coalesce(func.max(ROIVersion.version), 0)).where(
                ROIVersion.task_id == task_id
            )
        ).scalar_one()
        return int(current) + 1

    def current_mosaic(self, task_id: str) -> Artifact | None:
        return self.session.execute(
            select(Artifact).where(
                Artifact.task_id == task_id,
                Artifact.kind == "mosaic",
                Artifact.is_current.is_(True),
                Artifact.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

