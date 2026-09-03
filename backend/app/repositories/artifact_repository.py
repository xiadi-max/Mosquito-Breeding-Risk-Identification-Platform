from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.domain.models import Artifact


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, artifact_id: str) -> Artifact | None:
        return self.session.execute(
            select(Artifact)
            .options(joinedload(Artifact.task))
            .where(Artifact.id == artifact_id, Artifact.deleted_at.is_(None))
        ).scalar_one_or_none()

