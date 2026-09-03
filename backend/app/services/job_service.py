from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.fingerprint import canonical_json, fingerprint
from app.core.time import ensure_utc, utc_now
from app.domain.enums import JobStatus, JobType, TaskState
from app.domain.job_schemas import JobLinks, JobRead, JobResource, MosaicJobCreate
from app.domain.models import Job, JobEvent
from app.repositories.image_repository import ImageRepository
from app.repositories.job_repository import ACTIVE_JOB_STATUSES, JobRepository
from app.services.task_service import TaskService
from app.adapters.mosaic.opencv import opencv_runtime_available


def _json_object(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        return {"invalid_metadata": True}


def job_to_read(job: Job) -> JobRead:
    error = None
    if job.error_code:
        error = {
            "code": job.error_code,
            "detail": job.error_detail,
            "retryable": bool(job.error_retryable),
        }
    return JobRead(
        id=job.id,
        task_id=job.task_id,
        type=job.type,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        message=job.message,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        cancel_requested_at=(
            ensure_utc(job.cancel_requested_at) if job.cancel_requested_at else None
        ),
        error=error,
        result=_json_object(job.result_json),
        created_at=ensure_utc(job.created_at),
        started_at=ensure_utc(job.started_at) if job.started_at else None,
        finished_at=ensure_utc(job.finished_at) if job.finished_at else None,
    )


def job_resource(job: Job) -> JobResource:
    return JobResource(
        job=job_to_read(job),
        links=JobLinks(
            self=f"/api/v1/jobs/{job.id}",
            events=f"/api/v1/jobs/{job.id}/events",
            cancel=f"/api/v1/jobs/{job.id}/cancel",
        ),
    )


class JobService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = JobRepository(session)

    def get_model(self, job_id: str) -> Job:
        job = self.repository.get(job_id)
        if job is None:
            raise AppError(
                status_code=404,
                code="JOB_NOT_FOUND",
                title="作业不存在",
                detail="未找到指定作业。",
            )
        return job

    def get(self, job_id: str) -> JobResource:
        return job_resource(self.get_model(job_id))

    def create_mosaic(
        self,
        task_id: str,
        data: MosaicJobCreate,
        idempotency_key: str | None,
    ) -> tuple[JobResource, bool]:
        task = TaskService(self.session).get_model(task_id)
        if task.state != TaskState.RUNNING.value:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="当前任务不能执行拼接",
                detail="只有处理中的任务可以创建拼接作业。",
            )
        images = ImageRepository(self.session).list_for_task(task_id)
        if not images:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="缺少可拼接影像",
                detail="任务必须先上传影像；OpenCV SCANS 至少需要两张已校验影像。",
            )

        provider = self._resolve_mosaic_provider(data.provider)
        if provider == "opencv" and len(images) < 2:
            raise AppError(
                status_code=400,
                code="MOSAIC_INPUT_INSUFFICIENT",
                title="可拼接影像不足",
                detail="OpenCV SCANS 拼接至少需要两张来自同一连续区域的影像。",
            )
        unsupported = [
            image.display_name
            for image in images
            if provider == "opencv"
            and image.mime_type not in {"image/jpeg", "image/png"}
        ]
        if unsupported:
            names = "、".join(unsupported[:3])
            suffix = "等" if len(unsupported) > 3 else ""
            raise AppError(
                status_code=400,
                code="MOSAIC_INPUT_UNSUPPORTED",
                title="存在不支持的拼接影像",
                detail=f"OpenCV SCANS 仅支持 JPG、JPEG、PNG；不支持：{names}{suffix}。",
            )
        options = data.options.model_dump(mode="json")
        input_snapshot = {
            "operation": JobType.MOSAIC.value,
            "provider": provider,
            "options": options,
            "images": [
                {
                    "id": image.id,
                    "sha256": image.sha256,
                    "display_name": image.display_name,
                }
                for image in sorted(
                    images, key=lambda item: (item.display_name.casefold(), item.id)
                )
            ],
        }
        input_fingerprint = fingerprint(input_snapshot)
        request_snapshot = {
            "task_id": task_id,
            "type": JobType.MOSAIC.value,
            "provider": data.provider,
            "options": options,
        }
        request_hash = fingerprint(request_snapshot)
        effective_key = (idempotency_key or f"auto:{input_fingerprint}").strip()
        if not effective_key or len(effective_key) > 255:
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                title="幂等键无效",
                detail="Idempotency-Key 长度必须为 1–255 个字符。",
            )

        existing = self.repository.get_idempotent(
            task_id, JobType.MOSAIC.value, effective_key
        )
        if existing:
            if existing.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    title="幂等键已用于不同请求",
                    detail="请为不同的拼接参数使用新的 Idempotency-Key。",
                )
            return job_resource(existing), False

        active = self.repository.active_for_type(task_id, JobType.MOSAIC.value)
        if active:
            raise AppError(
                status_code=409,
                code="JOB_ALREADY_RUNNING",
                title="拼接作业正在执行",
                detail=f"任务已有未结束的拼接作业 {active.id}。",
            )

        now = utc_now()
        job = Job(
            id=str(uuid4()),
            task_id=task_id,
            type=JobType.MOSAIC.value,
            status=JobStatus.QUEUED.value,
            progress=0,
            current_step="queued",
            message="拼接作业已进入队列",
            input_json=canonical_json(input_snapshot),
            input_fingerprint=input_fingerprint,
            idempotency_key=effective_key,
            request_hash=request_hash,
            available_at=now,
            attempt_count=0,
            max_attempts=self.settings.job_max_retries,
            created_at=now,
        )
        self.session.add(job)
        try:
            self.session.flush()
        except IntegrityError:
            # A concurrent request may have inserted the same idempotency key.
            # Roll back this transaction and deterministically replay that row.
            self.session.rollback()
            concurrent = self.repository.get_idempotent(
                task_id, JobType.MOSAIC.value, effective_key
            )
            if concurrent is None:
                raise
            if concurrent.request_hash != request_hash:
                raise AppError(
                    status_code=409,
                    code="IDEMPOTENCY_KEY_REUSED",
                    title="幂等键已用于不同请求",
                    detail="请为不同的拼接参数使用新的 Idempotency-Key。",
                )
            return job_resource(concurrent), False
        self._add_event(job, "job.queued", {"message": job.message})
        self.session.commit()
        return job_resource(job), True

    def cancel(self, job_id: str) -> JobResource:
        job = self.get_model(job_id)
        status = JobStatus(job.status)
        if status.terminal:
            return job_resource(job)
        now = utc_now()
        if status == JobStatus.QUEUED:
            job.status = JobStatus.CANCELED.value
            job.current_step = "canceled"
            job.message = "作业已取消"
            job.cancel_requested_at = now
            job.finished_at = now
            self._add_event(job, "job.canceled", {"message": job.message})
        else:
            if job.cancel_requested_at is None:
                job.cancel_requested_at = now
                job.message = "已请求取消，等待 Worker 到达安全检查点"
                self._add_event(
                    job,
                    "job.step",
                    {"step": job.current_step, "message": job.message},
                )
        self.session.commit()
        return job_resource(job)

    def recover_expired(self) -> int:
        now = utc_now()
        expired = list(
            self.session.execute(
                select(Job).where(
                    Job.status.in_([JobStatus.CLAIMED.value, JobStatus.RUNNING.value]),
                    Job.lease_expires_at.is_not(None),
                    Job.lease_expires_at < now,
                )
            ).scalars()
        )
        for job in expired:
            if job.cancel_requested_at:
                self._set_canceled(job, "租约过期时检测到取消请求")
            elif job.attempt_count >= job.max_attempts:
                self._set_failed(
                    job,
                    code="JOB_LEASE_EXPIRED",
                    detail="Worker 租约过期且已达到最大尝试次数。",
                    retryable=False,
                )
            else:
                job.status = JobStatus.QUEUED.value
                job.progress = 0
                job.current_step = "recovered"
                job.message = "Worker 租约过期，作业已重新排队"
                job.worker_id = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                job.available_at = now
                self._add_event(
                    job,
                    "job.queued",
                    {"message": job.message, "recovered": True},
                )

        timed_out = list(
            self.session.execute(
                select(Job).where(
                    Job.status.in_([JobStatus.CLAIMED.value, JobStatus.RUNNING.value]),
                    Job.started_at.is_not(None),
                    Job.started_at
                    < now - timedelta(seconds=self.settings.mosaic_job_timeout_seconds),
                )
            ).scalars()
        )
        expired_ids = {job.id for job in expired}
        timed_out = [job for job in timed_out if job.id not in expired_ids]
        for job in timed_out:
            self._set_failed(
                job,
                code="JOB_TIMEOUT",
                detail="作业执行时间超过配置的最大时长。",
                retryable=False,
            )
        if expired or timed_out:
            self.session.commit()
        return len(expired) + len(timed_out)

    def claim_next(self, worker_id: str) -> Job | None:
        now = utc_now()
        candidate_id = self.session.execute(
            select(Job.id)
            .where(
                Job.status == JobStatus.QUEUED.value,
                Job.available_at <= now,
                Job.cancel_requested_at.is_(None),
            )
            .order_by(Job.available_at, Job.created_at, Job.id)
            .limit(1)
        ).scalar_one_or_none()
        if candidate_id is None:
            self.session.rollback()
            return None

        lease_expires = now + timedelta(seconds=self.settings.job_lease_seconds)
        result = self.session.execute(
            update(Job)
            .where(Job.id == candidate_id, Job.status == JobStatus.QUEUED.value)
            .values(
                status=JobStatus.CLAIMED.value,
                current_step="claimed",
                message="Worker 已领取作业",
                worker_id=worker_id,
                claimed_at=now,
                heartbeat_at=now,
                lease_expires_at=lease_expires,
                attempt_count=Job.attempt_count + 1,
            )
        )
        if result.rowcount != 1:
            self.session.rollback()
            return None
        self.session.commit()
        return self.repository.get(candidate_id)

    def mark_running(self, job_id: str, worker_id: str) -> Job:
        job = self._owned_active_job(job_id, worker_id)
        now = utc_now()
        job.status = JobStatus.RUNNING.value
        job.current_step = "starting"
        job.message = "Worker 开始执行作业"
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=self.settings.job_lease_seconds)
        self._add_event(job, "job.started", {"message": job.message})
        self.session.commit()
        return job

    def heartbeat(self, job_id: str, worker_id: str) -> bool:
        now = utc_now()
        result = self.session.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.worker_id == worker_id,
                Job.status.in_([JobStatus.CLAIMED.value, JobStatus.RUNNING.value]),
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=self.settings.job_lease_seconds),
            )
        )
        self.session.commit()
        return result.rowcount == 1

    def report_progress(
        self,
        job_id: str,
        worker_id: str,
        *,
        progress: int,
        step: str,
        message: str,
    ) -> None:
        job = self._owned_active_job(job_id, worker_id)
        previous_step = job.current_step
        job.progress = max(job.progress, min(99, max(0, progress)))
        job.current_step = step[:80]
        job.message = message[:500]
        now = utc_now()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=self.settings.job_lease_seconds)
        if previous_step != job.current_step:
            self._add_event(
                job,
                "job.step",
                {"step": job.current_step, "message": job.message},
            )
        self._add_event(
            job,
            "job.progress",
            {"progress": job.progress, "step": job.current_step, "message": job.message},
        )
        self.session.commit()

    def cancellation_requested(self, job_id: str) -> bool:
        return self.session.execute(
            select(Job.cancel_requested_at).where(Job.id == job_id)
        ).scalar_one_or_none() is not None

    def succeed(self, job_id: str, worker_id: str, result: dict[str, Any]) -> Job:
        job = self._owned_active_job(job_id, worker_id)
        if job.cancel_requested_at:
            self._set_canceled(job, "作业完成提交前收到取消请求")
        else:
            job.status = JobStatus.SUCCEEDED.value
            job.progress = 100
            job.current_step = "succeeded"
            job.message = "作业执行成功"
            job.result_json = canonical_json(result)
            job.error_code = None
            job.error_detail = None
            job.error_retryable = None
            job.finished_at = utc_now()
            job.worker_id = None
            job.lease_expires_at = None
            self._add_event(
                job,
                "job.succeeded",
                {"progress": 100, "result": result, "message": job.message},
            )
        self.session.commit()
        return job

    def fail(
        self,
        job_id: str,
        worker_id: str,
        *,
        code: str,
        detail: str,
        retryable: bool,
    ) -> Job:
        job = self._owned_active_job(job_id, worker_id)
        if job.cancel_requested_at:
            self._set_canceled(job, "Worker 已确认取消")
        elif retryable and job.attempt_count < job.max_attempts:
            delay_seconds = min(30, 2 ** max(0, job.attempt_count - 1))
            job.status = JobStatus.QUEUED.value
            job.progress = 0
            job.current_step = "retry_wait"
            job.message = f"执行失败，将在 {delay_seconds} 秒后重试"
            job.error_code = code[:80]
            job.error_detail = detail[:1000]
            job.error_retryable = True
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.available_at = utc_now() + timedelta(seconds=delay_seconds)
            self._add_event(
                job,
                "job.queued",
                {
                    "message": job.message,
                    "retry": True,
                    "attempt_count": job.attempt_count,
                },
            )
        else:
            self._set_failed(job, code=code, detail=detail, retryable=False)
        self.session.commit()
        return job

    def mark_canceled(self, job_id: str, worker_id: str, message: str) -> Job:
        job = self._owned_active_job(job_id, worker_id)
        self._set_canceled(job, message)
        self.session.commit()
        return job

    def _resolve_mosaic_provider(self, requested: str) -> str:
        provider = self.settings.mosaic_provider if requested == "auto" else requested
        configured = True
        if provider == "fake":
            configured = not self.settings.production_mode
        elif provider == "opencv":
            configured = opencv_runtime_available()
        if self.settings.production_mode and provider != self.settings.mosaic_provider:
            configured = False
        if not configured:
            raise AppError(
                status_code=503,
                code="MOSAIC_ENGINE_NOT_CONFIGURED",
                title="拼接引擎未配置",
                detail=f"拼接 Provider {provider} 当前不可用。",
            )
        return provider

    def _owned_active_job(self, job_id: str, worker_id: str) -> Job:
        job = self.get_model(job_id)
        if job.worker_id != worker_id or job.status not in {
            JobStatus.CLAIMED.value,
            JobStatus.RUNNING.value,
        }:
            raise RuntimeError("job is not owned by this worker")
        return job

    def _add_event(self, job: Job, event_type: str, data: dict[str, Any]) -> None:
        payload = {
            "job_id": job.id,
            "status": job.status,
            **data,
        }
        self.session.add(
            JobEvent(
                job_id=job.id,
                event_type=event_type,
                data_json=canonical_json(payload),
                created_at=utc_now(),
            )
        )

    def _set_canceled(self, job: Job, message: str) -> None:
        job.status = JobStatus.CANCELED.value
        job.current_step = "canceled"
        job.message = message[:500]
        job.finished_at = utc_now()
        job.worker_id = None
        job.lease_expires_at = None
        self._add_event(job, "job.canceled", {"message": job.message})

    def _set_failed(
        self, job: Job, *, code: str, detail: str, retryable: bool
    ) -> None:
        job.status = JobStatus.FAILED.value
        job.current_step = "failed"
        job.message = "作业执行失败"
        job.error_code = code[:80]
        job.error_detail = detail[:1000]
        job.error_retryable = retryable
        job.finished_at = utc_now()
        job.worker_id = None
        job.lease_expires_at = None
        self._add_event(
            job,
            "job.failed",
            {"error": {"code": job.error_code, "detail": job.error_detail}},
        )
