from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.adapters.mosaic import create_mosaic_engine
from app.adapters.mosaic.base import MosaicCanceled, MosaicEngineError, MosaicSource
from app.core.config import Settings
from app.core.fingerprint import canonical_json
from app.core.security import resolve_storage_path
from app.core.time import utc_now
from app.domain.enums import ArtifactKind, JobStatus
from app.domain.models import Artifact, Image, Job, Task
from app.services.job_service import JobService
from app.services.workflow_service import WorkflowService


class JobExecutionError(Exception):
    def __init__(self, code: str, detail: str, *, retryable: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


class JobCanceled(Exception):
    pass


def _file_metadata(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class MosaicService:
    def __init__(
        self, factory: sessionmaker[Session], settings: Settings
    ) -> None:
        self.factory = factory
        self.settings = settings

    def execute(self, job_id: str, worker_id: str) -> dict[str, Any]:
        job, sources, provider, options = self._load_inputs(job_id, worker_id)
        work_directory = resolve_storage_path(
            self.settings.resolved_storage_root, f"tasks/{job.task_id}/tmp/{job.id}"
        )
        if work_directory.exists():
            shutil.rmtree(work_directory)
        work_directory.mkdir(parents=True, exist_ok=True)

        def progress(value: int, step: str, message: str) -> None:
            with self.factory() as session:
                JobService(session, self.settings).report_progress(
                    job_id,
                    worker_id,
                    progress=value,
                    step=step,
                    message=message,
                )

        def is_canceled() -> bool:
            with self.factory() as session:
                current = JobService(session, self.settings).get_model(job_id)
                if current.cancel_requested_at is not None:
                    return True
                if current.started_at is None:
                    return False
                from app.core.time import ensure_utc

                elapsed = (utc_now() - ensure_utc(current.started_at)).total_seconds()
                if elapsed > self.settings.mosaic_job_timeout_seconds:
                    raise MosaicEngineError(
                        "JOB_TIMEOUT",
                        "拼接作业执行时间超过配置的最大时长。",
                        retryable=False,
                    )
                return False

        engine = create_mosaic_engine(provider, self.settings)
        try:
            engine.validate()
            result = engine.run(
                sources,
                work_directory,
                options,
                progress,
                is_canceled,
            )
            if is_canceled():
                raise JobCanceled
            return self._persist_result(job_id, worker_id, provider, options, result)
        except MosaicCanceled as exc:
            raise JobCanceled from exc
        except MosaicEngineError as exc:
            raise JobExecutionError(
                exc.code, exc.detail, retryable=exc.retryable
            ) from exc

    def _load_inputs(
        self, job_id: str, worker_id: str
    ) -> tuple[Job, list[MosaicSource], str, dict[str, Any]]:
        pending_sources: list[tuple[str, Path, str, bool, str]] = []
        with self.factory() as session:
            job = session.get(Job, job_id)
            if (
                job is None
                or job.worker_id != worker_id
                or job.status != JobStatus.RUNNING.value
            ):
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 已失去作业租约。")
            snapshot = json.loads(job.input_json)
            image_ids = [item["id"] for item in snapshot["images"]]
            images = list(
                session.execute(
                    select(Image)
                    .options(joinedload(Image.artifact))
                    .where(Image.task_id == job.task_id, Image.id.in_(image_ids))
                ).scalars()
            )
            by_id = {image.id: image for image in images}
            for item in snapshot["images"]:
                image = by_id.get(item["id"])
                if image is None or image.sha256 != item["sha256"]:
                    raise JobExecutionError(
                        "MOSAIC_INPUT_STALE",
                        "拼接输入影像已变化，请创建新的拼接作业。",
                    )
                path = resolve_storage_path(
                    self.settings.resolved_storage_root, image.artifact.relative_path
                )
                pending_sources.append(
                    (
                        image.id,
                        path,
                        image.sha256,
                        image.gps_lat is not None and image.gps_lon is not None,
                        image.display_name,
                    )
                )
            session.expunge(job)
        # File existence and hashing happen after the database transaction closes.
        sources: list[MosaicSource] = []
        for image_id, path, expected_sha256, has_gps, display_name in pending_sources:
            if not path.is_file():
                raise JobExecutionError(
                    "ARTIFACT_NOT_FOUND", "一张或多张原始影像文件不存在。"
                )
            actual_sha256, _ = _file_metadata(path)
            if actual_sha256 != expected_sha256:
                raise JobExecutionError(
                    "ARTIFACT_INTEGRITY_ERROR",
                    f"影像 {image_id} 的文件哈希与数据库记录不一致。",
                )
            sources.append(
                MosaicSource(
                    image_id=image_id,
                    path=path,
                    sha256=expected_sha256,
                    has_gps=has_gps,
                    display_name=display_name,
                )
            )
        return job, sources, snapshot["provider"], snapshot["options"]

    def _persist_result(
        self,
        job_id: str,
        worker_id: str,
        provider: str,
        options: dict[str, Any],
        result,
    ) -> dict[str, Any]:
        with self.factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobExecutionError("JOB_NOT_FOUND", "作业在提交结果前被删除。")
            if job.worker_id != worker_id or job.status != JobStatus.RUNNING.value:
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 已失去作业租约。")
            if job.cancel_requested_at:
                raise JobCanceled
            task_id = job.task_id

        final_directory = resolve_storage_path(
            self.settings.resolved_storage_root,
            f"tasks/{task_id}/mosaic/{job_id}",
        )
        final_directory.mkdir(parents=True, exist_ok=True)
        quality_source = result.mosaic_path.parent / "quality.json"
        quality_source.write_text(
            canonical_json(result.quality_summary), encoding="utf-8"
        )
        outputs = [
            (
                ArtifactKind.MOSAIC.value,
                result.mosaic_path,
                result.mosaic_filename,
                result.mosaic_mime_type,
                result.width,
                result.height,
            ),
            (
                ArtifactKind.MOSAIC_PREVIEW.value,
                result.preview_path,
                "preview.jpg",
                "image/jpeg",
                None,
                None,
            ),
            (
                ArtifactKind.MOSAIC_QUALITY.value,
                quality_source,
                "quality.json",
                "application/json",
                None,
                None,
            ),
        ]
        artifact_specs: list[dict[str, Any]] = []
        artifact_ids: dict[str, str] = {}
        moved_paths: list[Path] = []
        try:
            for kind, source, filename, mime_type, width, height in outputs:
                destination = final_directory / filename
                os.replace(source, destination)
                moved_paths.append(destination)
                sha256, size_bytes = _file_metadata(destination)
                artifact_id = str(uuid4())
                relative_path = destination.relative_to(
                    self.settings.resolved_storage_root
                ).as_posix()
                artifact_specs.append(
                    {
                        "id": artifact_id,
                        "kind": kind,
                        "relative_path": relative_path,
                        "sha256": sha256,
                        "size_bytes": size_bytes,
                        "mime_type": mime_type,
                        "width": width,
                        "height": height,
                    }
                )
                artifact_ids[kind] = artifact_id

            payload = {
                "mosaic_artifact_id": artifact_ids[ArtifactKind.MOSAIC.value],
                "preview_artifact_id": artifact_ids[
                    ArtifactKind.MOSAIC_PREVIEW.value
                ],
                "quality_artifact_id": artifact_ids[
                    ArtifactKind.MOSAIC_QUALITY.value
                ],
                "width": result.width,
                "height": result.height,
                "provider": provider,
                "quality": result.quality_summary,
            }
            # Only metadata persistence and state transitions occur in this short txn.
            with self.factory() as session:
                current_job = session.get(Job, job_id)
                if (
                    current_job is None
                    or current_job.worker_id != worker_id
                    or current_job.status != JobStatus.RUNNING.value
                ):
                    raise JobExecutionError(
                        "JOB_OWNERSHIP_LOST", "Worker 在提交阶段失去作业租约。"
                    )
                if current_job.cancel_requested_at:
                    raise JobCanceled
                session.execute(
                    update(Artifact)
                    .where(
                        Artifact.task_id == task_id,
                        Artifact.kind.in_(
                            [
                                ArtifactKind.MOSAIC.value,
                                ArtifactKind.MOSAIC_PREVIEW.value,
                                ArtifactKind.MOSAIC_QUALITY.value,
                            ]
                        ),
                        Artifact.is_current.is_(True),
                    )
                    .values(is_current=False)
                )
                WorkflowService(session).invalidate_from_mosaic(task_id)
                for spec in artifact_specs:
                    session.add(
                        Artifact(
                            **spec,
                            task_id=task_id,
                            job_id=job_id,
                            metadata_json=canonical_json(
                                {
                                    "provider": provider,
                                    "options": options,
                                    "quality": result.quality_summary,
                                }
                            ),
                            is_current=True,
                            created_at=utc_now(),
                        )
                    )
                session.execute(
                    update(Task)
                    .where(Task.id == task_id)
                    .values(version=Task.version + 1, updated_at=utc_now())
                )
                JobService(session, self.settings).succeed(job_id, worker_id, payload)

            shutil.rmtree(result.mosaic_path.parent, ignore_errors=True)
            return payload
        except Exception:
            for path in moved_paths:
                path.unlink(missing_ok=True)
            raise
