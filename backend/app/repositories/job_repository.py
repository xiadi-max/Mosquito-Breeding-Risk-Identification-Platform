from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.models import Job, JobEvent


ACTIVE_JOB_STATUSES = ("queued", "claimed", "running")


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: str) -> Job | None:
        return self.session.get(Job, job_id)

    def get_idempotent(
        self, task_id: str, job_type: str, idempotency_key: str
    ) -> Job | None:
        return self.session.execute(
            select(Job).where(
                Job.task_id == task_id,
                Job.type == job_type,
                Job.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def active_for_type(self, task_id: str, job_type: str) -> Job | None:
        return self.session.execute(
            select(Job)
            .where(
                Job.task_id == task_id,
                Job.type == job_type,
                Job.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def active_for_task(self, task_id: str) -> Job | None:
        return self.session.execute(
            select(Job)
            .where(Job.task_id == task_id, Job.status.in_(ACTIVE_JOB_STATUSES))
            .order_by(Job.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def events_after(
        self, job_id: str, event_id: int, *, limit: int = 100
    ) -> list[JobEvent]:
        return list(
            self.session.execute(
                select(JobEvent)
                .where(JobEvent.job_id == job_id, JobEvent.id > event_id)
                .order_by(JobEvent.id)
                .limit(limit)
            ).scalars()
        )

    def latest_event_id(self, job_id: str) -> int:
        return int(
            self.session.execute(
                select(func.coalesce(func.max(JobEvent.id), 0)).where(
                    JobEvent.job_id == job_id
                )
            ).scalar_one()
        )
