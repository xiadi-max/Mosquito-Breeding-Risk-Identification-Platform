from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import time
from datetime import UTC, datetime
from threading import Event
from threading import Thread
from uuid import uuid4

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings, get_settings
from app.core.db import create_db_engine, create_session_factory, get_schema_revision
from app.core.logging import configure_logging
from app.domain.enums import WorkerStatus
from app.domain.enums import JobType
from app.domain.models import WorkerHeartbeat
from app.services.job_service import JobService
from app.services.mosaic_service import JobCanceled, JobExecutionError, MosaicService
from app.services.grid_service import GridJobExecutor
from app.services.inference_service import InferenceJobExecutor
from app.services.risk_service import RiskJobExecutor
from app.services.decision_service import DecisionJobExecutor
from app.services.export_service import ExportJobExecutor


logger = logging.getLogger(__name__)


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"


def _write_heartbeat(
    factory,
    *,
    worker_id: str,
    status: WorkerStatus,
    started_at: datetime,
    settings: Settings,
) -> None:
    now = datetime.now(UTC)
    capabilities = json.dumps(
        {
            "mosaic_provider": settings.mosaic_provider,
            "detector_provider": settings.detector_provider,
            "decision_provider": settings.decision_provider,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with factory() as session:
        bind = session.get_bind()
        if bind.dialect.name == "sqlite":
            statement = sqlite_insert(WorkerHeartbeat).values(
                worker_id=worker_id,
                process_id=os.getpid(),
                status=status.value,
                capabilities_json=capabilities,
                started_at=started_at,
                last_seen_at=now,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[WorkerHeartbeat.worker_id],
                set_={
                    "status": status.value,
                    "capabilities_json": capabilities,
                    "last_seen_at": now,
                },
            )
            session.execute(statement)
        else:
            session.merge(
                WorkerHeartbeat(
                    worker_id=worker_id,
                    process_id=os.getpid(),
                    status=status.value,
                    capabilities_json=capabilities,
                    started_at=started_at,
                    last_seen_at=now,
                )
            )
        session.commit()


class LeaseHeartbeat:
    def __init__(self, factory, settings: Settings, job_id: str, worker_id: str) -> None:
        self.factory = factory
        self.settings = settings
        self.job_id = job_id
        self.worker_id = worker_id
        self.stop_event = Event()
        self.thread = Thread(target=self._run, name=f"lease-{job_id[:8]}", daemon=True)

    def __enter__(self) -> "LeaseHeartbeat":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self) -> None:
        interval = max(1.0, self.settings.job_lease_seconds / 3)
        while not self.stop_event.wait(interval):
            try:
                with self.factory() as session:
                    if not JobService(session, self.settings).heartbeat(
                        self.job_id, self.worker_id
                    ):
                        return
            except SQLAlchemyError:
                logger.exception(
                    "job lease heartbeat failed",
                    extra={
                        "job_id": self.job_id,
                        "worker_id": self.worker_id,
                        "error_code": "DATABASE_ERROR",
                    },
                )


def _execute_job(factory, settings: Settings, job, worker_id: str) -> None:
    with factory() as session:
        JobService(session, settings).mark_running(job.id, worker_id)
    with LeaseHeartbeat(factory, settings, job.id, worker_id):
        if job.type == JobType.MOSAIC.value:
            MosaicService(factory, settings).execute(job.id, worker_id)
            return
        if job.type == JobType.GRID_GENERATE.value:
            GridJobExecutor(factory, settings).execute(job.id, worker_id)
            return
        if job.type == JobType.INFERENCE.value:
            InferenceJobExecutor(factory, settings).execute(job.id, worker_id)
            return
        if job.type == JobType.RISK_ANALYSIS.value:
            RiskJobExecutor(factory, settings).execute(job.id, worker_id)
            return
        if job.type == JobType.DECISION_GENERATE.value:
            DecisionJobExecutor(factory, settings).execute(job.id, worker_id)
            return
        if job.type in {JobType.EXPORT_CSV.value, JobType.EXPORT_XLSX.value, JobType.EXPORT_PDF.value}:
            ExportJobExecutor(factory, settings).execute(job.id, worker_id)
            return
        raise JobExecutionError(
            "JOB_TYPE_NOT_SUPPORTED",
            f"Worker 尚未注册作业类型 {job.type} 的处理器。",
            retryable=False,
        )


def run_worker(*, once: bool = False, settings: Settings | None = None) -> int:
    active_settings = settings or get_settings()
    configure_logging(active_settings.log_level)
    engine = create_db_engine(active_settings)
    revision = get_schema_revision(engine)
    if revision is None:
        logger.error(
            "database is not migrated; run alembic upgrade head",
            extra={"error_code": "DATABASE_NOT_MIGRATED"},
        )
        engine.dispose()
        return 2

    factory = create_session_factory(engine)
    worker_id = _worker_id()
    started_at = datetime.now(UTC)
    stop_event = Event()

    def request_stop(*_: object) -> None:
        stop_event.set()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(signal_name, request_stop)
        except (OSError, ValueError):
            pass

    logger.info("worker started", extra={"worker_id": worker_id})
    try:
        while not stop_event.is_set():
            with factory() as session:
                recovered = JobService(session, active_settings).recover_expired()
            if recovered:
                logger.warning(
                    "expired jobs recovered",
                    extra={"worker_id": worker_id, "recovered_count": recovered},
                )

            _write_heartbeat(
                factory,
                worker_id=worker_id,
                status=WorkerStatus.IDLE,
                started_at=started_at,
                settings=active_settings,
            )
            with factory() as session:
                job = JobService(session, active_settings).claim_next(worker_id)
            if job is not None:
                _write_heartbeat(
                    factory,
                    worker_id=worker_id,
                    status=WorkerStatus.BUSY,
                    started_at=started_at,
                    settings=active_settings,
                )
                logger.info(
                    "job claimed",
                    extra={
                        "worker_id": worker_id,
                        "job_id": job.id,
                        "task_id": job.task_id,
                        "job_type": job.type,
                    },
                )
                try:
                    _execute_job(factory, active_settings, job, worker_id)
                except JobCanceled:
                    with factory() as session:
                        JobService(session, active_settings).mark_canceled(
                            job.id, worker_id, "Worker 已在安全检查点取消作业"
                        )
                except JobExecutionError as exc:
                    with factory() as session:
                        JobService(session, active_settings).fail(
                            job.id,
                            worker_id,
                            code=exc.code,
                            detail=exc.detail,
                            retryable=exc.retryable,
                        )
                except Exception as exc:
                    logger.exception(
                        "unexpected job failure",
                        extra={
                            "worker_id": worker_id,
                            "job_id": job.id,
                            "task_id": job.task_id,
                            "error_code": "JOB_FAILED",
                        },
                    )
                    try:
                        with factory() as session:
                            JobService(session, active_settings).fail(
                                job.id,
                                worker_id,
                                code="JOB_FAILED",
                                detail=f"{type(exc).__name__}: 作业发生未预期错误。",
                                retryable=False,
                            )
                    except Exception:
                        logger.exception(
                            "failed to persist job failure",
                            extra={"worker_id": worker_id, "job_id": job.id},
                        )
                finally:
                    _write_heartbeat(
                        factory,
                        worker_id=worker_id,
                        status=WorkerStatus.IDLE,
                        started_at=started_at,
                        settings=active_settings,
                    )
            if once:
                break
            if job is None:
                stop_event.wait(active_settings.job_poll_interval)
    except SQLAlchemyError:
        logger.exception(
            "worker heartbeat failed",
            extra={"worker_id": worker_id, "error_code": "DATABASE_ERROR"},
        )
        return 1
    finally:
        try:
            _write_heartbeat(
                factory,
                worker_id=worker_id,
                status=WorkerStatus.STOPPING,
                started_at=started_at,
                settings=active_settings,
            )
        except SQLAlchemyError:
            logger.exception("failed to write final worker heartbeat")
        engine.dispose()
        logger.info("worker stopped", extra={"worker_id": worker_id})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="MosquitoMapper compute worker")
    parser.add_argument("--once", action="store_true", help="write one heartbeat and exit")
    args = parser.parse_args()
    return run_worker(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
