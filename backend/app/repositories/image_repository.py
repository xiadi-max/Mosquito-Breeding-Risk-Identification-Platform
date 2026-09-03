from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.domain.models import Image


class ImageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_for_task(self, task_id: str, image_id: str) -> Image | None:
        return self.session.execute(
            select(Image)
            .options(joinedload(Image.artifact))
            .where(Image.task_id == task_id, Image.id == image_id)
        ).scalar_one_or_none()

    def get_by_sha256(self, task_id: str, sha256: str) -> Image | None:
        return self.session.execute(
            select(Image).where(Image.task_id == task_id, Image.sha256 == sha256)
        ).scalar_one_or_none()

    def list_for_task(self, task_id: str) -> list[Image]:
        return list(
            self.session.execute(
                select(Image)
                .where(Image.task_id == task_id)
                .order_by(Image.created_at.desc(), Image.id.desc())
            ).scalars()
        )

    def total_bytes(self, task_id: str) -> int:
        return int(
            self.session.execute(
                select(func.coalesce(func.sum(Image.size_bytes), 0)).where(
                    Image.task_id == task_id
                )
            ).scalar_one()
        )

