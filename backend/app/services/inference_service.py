from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from app.adapters.detection import create_detector
from app.adapters.detection.base import DetectParams, DetectorError, ImageInput
from app.core.config import Settings
from app.core.errors import AppError
from app.core.fingerprint import canonical_json, fingerprint
from app.core.security import resolve_storage_path
from app.core.time import utc_now
from app.domain.enums import ArtifactKind, DetectionState, DerivedStatus, JobStatus, JobType, TaskState
from app.domain.inference_schemas import InferenceJobCreate
from app.domain.job_schemas import JobResource
from app.domain.models import Artifact, Detection, GridPlan, GridTile, InferenceRun, Job, JobEvent, ModelVersion, Task
from app.repositories.grid_repository import GridRepository
from app.repositories.inference_repository import InferenceRepository
from app.repositories.job_repository import JobRepository
from app.services.detection_geometry import MappedPrediction, class_aware_nms, tile_box_to_mosaic
from app.services.job_service import JobService, job_resource
from app.services.mosaic_service import JobCanceled, JobExecutionError, _file_metadata
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


class InferenceService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = InferenceRepository(session)

    def create_job(
        self, task_id: str, data: InferenceJobCreate, idempotency_key: str | None
    ) -> tuple[JobResource, bool]:
        task = TaskService(self.session).get_model(task_id)
        if task.state != TaskState.RUNNING.value:
            raise self._state_error("只有处理中的任务可以创建推理作业。")
        grid = GridRepository(self.session).get(data.grid_plan_id)
        if grid is None or grid.task_id != task_id or grid.status != DerivedStatus.CURRENT.value:
            raise self._state_error("只能使用当前有效网格计划进行推理。")
        provider = self.settings.detector_provider if data.provider == "auto" else data.provider
        if self.settings.production_mode and provider != self.settings.detector_provider:
            raise self._model_error(provider)
        if provider == "fake" and self.settings.production_mode:
            raise self._model_error(provider)
        try:
            metadata = create_detector(provider, self.settings).metadata()
        except DetectorError as exc:
            raise self._model_error(provider, exc.detail) from exc
        model = self._ensure_model(metadata)
        if data.model_version_id and data.model_version_id != model.id:
            requested = self.repository.model(data.model_version_id)
            if requested is None or not requested.active or requested.provider != provider:
                raise self._model_error(provider, "指定模型版本不存在或未启用。")
            model = requested

        thresholds = {
            "infer_min_confidence": data.infer_min_confidence,
            "review_threshold": data.review_threshold,
            "auto_accept_threshold": data.auto_accept_threshold,
        }
        input_snapshot = {
            "operation": JobType.INFERENCE.value,
            "grid_plan_id": grid.id,
            "grid_fingerprint": grid.fingerprint,
            "model_version_id": model.id,
            "model_identity": [model.provider, model.weights_sha256, model.code_version],
            "provider": provider,
            "thresholds": thresholds,
            "nms_iou": data.nms_iou,
        }
        input_hash = fingerprint(input_snapshot)
        request_hash = fingerprint({"task_id": task_id, **data.model_dump(mode="json")})
        key = (idempotency_key or f"auto:{input_hash}").strip()
        if not key or len(key) > 255:
            raise AppError(status_code=422, code="VALIDATION_ERROR", title="幂等键无效", detail="Idempotency-Key 长度必须为 1–255 个字符。")
        jobs = JobRepository(self.session)
        existing = jobs.get_idempotent(task_id, JobType.INFERENCE.value, key)
        if existing:
            if existing.request_hash != request_hash:
                raise AppError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", title="幂等键已用于不同请求", detail="请为不同推理参数使用新的 Idempotency-Key。")
            return job_resource(existing), False
        active = jobs.active_for_type(task_id, JobType.INFERENCE.value)
        if active:
            raise AppError(status_code=409, code="JOB_ALREADY_RUNNING", title="推理作业正在执行", detail=f"任务已有未结束的推理作业 {active.id}。")
        now = utc_now()
        job = Job(id=str(uuid4()), task_id=task_id, type=JobType.INFERENCE.value,
                  status=JobStatus.QUEUED.value, progress=0, current_step="queued",
                  message="推理作业已进入队列", input_json=canonical_json(input_snapshot),
                  input_fingerprint=input_hash, idempotency_key=key, request_hash=request_hash,
                  available_at=now, attempt_count=0, max_attempts=self.settings.job_max_retries,
                  created_at=now)
        self.session.add(job)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            concurrent = jobs.get_idempotent(task_id, JobType.INFERENCE.value, key)
            if concurrent is None:
                raise
            if concurrent.request_hash != request_hash:
                raise AppError(status_code=409, code="IDEMPOTENCY_KEY_REUSED", title="幂等键已用于不同请求", detail="请为不同推理参数使用新的 Idempotency-Key。")
            return job_resource(concurrent), False
        self.session.add(JobEvent(job_id=job.id, event_type="job.queued", data_json=canonical_json({"job_id": job.id, "status": job.status, "message": job.message}), created_at=now))
        self.session.commit()
        return job_resource(job), True

    def _ensure_model(self, metadata) -> ModelVersion:
        existing = self.repository.active_model(metadata.provider)
        if existing and (existing.weights_sha256, existing.code_version) == (metadata.weights_sha256, metadata.code_version):
            return existing
        if existing:
            existing.active = False
        model = ModelVersion(id=str(uuid4()), name=metadata.name, provider=metadata.provider,
            weights_sha256=metadata.weights_sha256, weights_label=metadata.weights_label,
            input_size=metadata.input_size, class_map_json=canonical_json(metadata.class_map),
            device=metadata.device, code_version=metadata.code_version,
            metadata_json=canonical_json(metadata.metadata), active=True, created_at=utc_now())
        self.session.add(model)
        self.session.flush()
        return model

    @staticmethod
    def _state_error(detail: str):
        return AppError(status_code=400, code="INVALID_WORKFLOW_STATE", title="当前不能执行推理", detail=detail)

    @staticmethod
    def _model_error(provider: str, detail: str | None = None):
        return AppError(status_code=503, code="MODEL_NOT_CONFIGURED", title="检测模型未配置", detail=detail or f"检测 Provider {provider} 当前不可用。")


class InferenceJobExecutor:
    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings

    def execute(self, job_id: str, worker_id: str) -> dict[str, Any]:
        with self.factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.worker_id != worker_id or job.status != JobStatus.RUNNING.value:
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 已失去推理作业租约。")
            snapshot = json.loads(job.input_json)
            grid = session.execute(select(GridPlan).options(selectinload(GridPlan.tiles), joinedload(GridPlan.mosaic_artifact)).where(GridPlan.id == snapshot["grid_plan_id"])).scalar_one_or_none()
            if grid is None or grid.task_id != job.task_id or grid.status != DerivedStatus.CURRENT.value or grid.fingerprint != snapshot["grid_fingerprint"]:
                raise JobExecutionError("INFERENCE_INPUT_STALE", "网格计划已变化，请重新创建推理作业。")
            mosaic_path = resolve_storage_path(self.settings.resolved_storage_root, grid.mosaic_artifact.relative_path)
            model = session.get(ModelVersion, snapshot["model_version_id"])
            if model is None or not model.active:
                raise JobExecutionError("MODEL_NOT_CONFIGURED", "推理模型版本已失效。")
            task_id, mosaic_width, mosaic_height = job.task_id, grid.mosaic_artifact.width, grid.mosaic_artifact.height
            tiles = list(sorted(grid.tiles, key=lambda item: item.code))
        if not mosaic_path.is_file() or mosaic_width is None or mosaic_height is None:
            raise JobExecutionError("ARTIFACT_NOT_FOUND", "当前拼接图文件不存在。")

        self._progress(job_id, worker_id, 8, "load_model", "正在加载检测模型")
        try:
            detector = create_detector(snapshot["provider"], self.settings)
            detector.warmup()
        except DetectorError as exc:
            raise JobExecutionError(exc.code, exc.detail, retryable=exc.retryable) from exc
        self._progress(job_id, worker_id, 20, "load_tiles", "正在从拼接图读取网格")
        inputs: list[ImageInput] = []
        with Image.open(mosaic_path) as opened:
            mosaic = opened.convert("RGB")
            for tile in tiles:
                crop = mosaic.crop((tile.source_x1, tile.source_y1, tile.source_x2, tile.source_y2))
                canvas = Image.new("RGB", (grid.tile_size, grid.tile_size), (0, 0, 0))
                canvas.paste(crop, (tile.pad_left, tile.pad_top))
                inputs.append(ImageInput(tile_id=tile.id, tile_code=tile.code, image=canvas))
        self._progress(job_id, worker_id, 40, "detect", "正在执行目标检测")
        try:
            raw = detector.predict(inputs, DetectParams(min_confidence=snapshot["thresholds"]["infer_min_confidence"], input_size=model.input_size))
        except DetectorError as exc:
            raise JobExecutionError(exc.code, exc.detail, retryable=exc.retryable) from exc
        finally:
            for item in inputs:
                item.image.close()
        tile_map = {tile.id: tile for tile in tiles}
        mapped: list[MappedPrediction] = []
        for item in raw:
            tile = tile_map[item.tile_id]
            transform = json.loads(tile.tile_to_mosaic_json)
            try:
                mosaic_box = tile_box_to_mosaic(item.box, mosaic_width=mosaic_width, mosaic_height=mosaic_height, **transform)
            except ValueError:
                continue
            mapped.append(MappedPrediction(item.tile_id, item.tile_code, item.class_id, item.class_name, item.confidence, item.box, mosaic_box))
        self._progress(job_id, worker_id, 62, "nms", "正在执行跨网格类别感知去重")
        retained = class_aware_nms(mapped, snapshot["nms_iou"])
        raw_path = self._write_predictions(
            task_id, job_id, snapshot["provider"], raw, retained
        )
        crop_specs = self._write_review_crops(
            task_id, job_id, mosaic_path, retained
        )
        self._progress(job_id, worker_id, 82, "persist", "正在持久化推理结果")
        result = self._persist(
            job_id, worker_id, snapshot, retained, raw_path, crop_specs
        )
        self._progress(job_id, worker_id, 95, "review_queue", "已生成待复核队列")
        with self.factory() as session:
            JobService(session, self.settings).succeed(job_id, worker_id, result)
        return result

    def _write_predictions(
        self, task_id: str, job_id: str, provider: str, raw, retained
    ):
        directory = resolve_storage_path(self.settings.resolved_storage_root, f"tasks/{task_id}/inference/{job_id}")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "raw_predictions.json"
        path.write_text(canonical_json({"demo": provider == "fake", "raw": [{"tile_id": p.tile_id, "class_id": p.class_id, "class_name": p.class_name, "confidence": p.confidence, "box": p.box} for p in raw], "retained_count": len(retained)}), encoding="utf-8")
        return path

    def _write_review_crops(
        self,
        task_id: str,
        job_id: str,
        mosaic_path,
        retained: list[MappedPrediction],
    ) -> list[dict[str, Any]]:
        directory = resolve_storage_path(
            self.settings.resolved_storage_root,
            f"tasks/{task_id}/inference/{job_id}/review_crops",
        )
        directory.mkdir(parents=True, exist_ok=True)
        specs: list[dict[str, Any]] = []
        with Image.open(mosaic_path) as opened:
            mosaic = opened.convert("RGB")
            for index, item in enumerate(retained, 1):
                x1, y1, x2, y2 = item.mosaic_box
                margin = max(8, int(max(x2 - x1, y2 - y1) * 0.15))
                bounds = (
                    max(0, int(x1) - margin),
                    max(0, int(y1) - margin),
                    min(mosaic.width, int(x2 + 0.999) + margin),
                    min(mosaic.height, int(y2 + 0.999) + margin),
                )
                crop = mosaic.crop(bounds)
                path = directory / f"C-{index:03d}.jpg"
                crop.save(path, format="JPEG", quality=90, optimize=True)
                sha256, size = _file_metadata(path)
                specs.append(
                    {
                        "id": str(uuid4()),
                        "path": path,
                        "sha256": sha256,
                        "size_bytes": size,
                        "width": crop.width,
                        "height": crop.height,
                    }
                )
                crop.close()
        return specs

    def _persist(
        self,
        job_id: str,
        worker_id: str,
        snapshot: dict,
        retained: list[MappedPrediction],
        raw_path,
        crop_specs: list[dict[str, Any]],
    ) -> dict:
        sha256, size = _file_metadata(raw_path)
        artifact_id, run_id = str(uuid4()), str(uuid4())
        thresholds = snapshot["thresholds"]
        counts = {"total": len(retained), "accepted": 0, "pending": 0, "rejected": 0, "discarded": 0}
        with self.factory() as session:
            job = session.get(Job, job_id)
            if job is None or job.worker_id != worker_id or job.status != JobStatus.RUNNING.value:
                raise JobExecutionError("JOB_OWNERSHIP_LOST", "Worker 在提交推理结果前失去租约。")
            if job.cancel_requested_at:
                raise JobCanceled
            grid = session.get(GridPlan, snapshot["grid_plan_id"])
            if grid is None or grid.status != DerivedStatus.CURRENT.value:
                raise JobExecutionError("INFERENCE_INPUT_STALE", "网格计划已失效。")
            session.execute(update(InferenceRun).where(InferenceRun.task_id == job.task_id, InferenceRun.status == DerivedStatus.CURRENT.value).values(status=DerivedStatus.STALE.value))
            session.execute(update(Artifact).where(Artifact.task_id == job.task_id, Artifact.kind.in_([ArtifactKind.PREDICTIONS_JSON.value, ArtifactKind.REVIEW_CROP.value]), Artifact.is_current.is_(True)).values(is_current=False))
            artifact = Artifact(id=artifact_id, task_id=job.task_id, job_id=job_id, kind=ArtifactKind.PREDICTIONS_JSON.value,
                relative_path=raw_path.relative_to(self.settings.resolved_storage_root).as_posix(), sha256=sha256,
                size_bytes=size, mime_type="application/json", metadata_json=canonical_json({"provider": snapshot["provider"], "demo": snapshot["provider"] == "fake"}),
                is_current=True, created_at=utc_now())
            session.add(artifact)
            for index, spec in enumerate(crop_specs, 1):
                session.add(
                    Artifact(
                        id=spec["id"],
                        task_id=job.task_id,
                        job_id=job_id,
                        kind=ArtifactKind.REVIEW_CROP.value,
                        relative_path=spec["path"].relative_to(
                            self.settings.resolved_storage_root
                        ).as_posix(),
                        sha256=spec["sha256"],
                        size_bytes=spec["size_bytes"],
                        mime_type="image/jpeg",
                        width=spec["width"],
                        height=spec["height"],
                        metadata_json=canonical_json({"detection_code": f"C-{index:03d}"}),
                        is_current=True,
                        created_at=utc_now(),
                    )
                )
            run = InferenceRun(id=run_id, task_id=job.task_id, grid_plan_id=grid.id,
                model_version_id=snapshot["model_version_id"], job_id=job_id,
                predictions_artifact_id=artifact_id, thresholds_json=canonical_json(thresholds),
                nms_iou=snapshot["nms_iou"], input_fingerprint=job.input_fingerprint,
                status=DerivedStatus.CURRENT.value, stats_json="{}", review_snapshot_version=0,
                created_at=utc_now())
            session.add(run)
            for index, item in enumerate(retained, 1):
                state = DetectionState.ACCEPTED.value if item.confidence >= thresholds["auto_accept_threshold"] else DetectionState.PENDING.value
                counts[state] += 1
                mosaic_box = {"x1": item.mosaic_box[0], "y1": item.mosaic_box[1], "x2": item.mosaic_box[2], "y2": item.mosaic_box[3]}
                session.add(Detection(id=str(uuid4()), inference_run=run, code=f"C-{index:03d}",
                    class_id=item.class_id, class_name=item.class_name, confidence=item.confidence,
                    source_grid_tile_id=item.tile_id, tile_box_json=canonical_json({"x1": item.tile_box[0], "y1": item.tile_box[1], "x2": item.tile_box[2], "y2": item.tile_box[3]}),
                    crop_artifact_id=crop_specs[index - 1]["id"],
                    mosaic_box_json=canonical_json(mosaic_box), center_x=(item.mosaic_box[0]+item.mosaic_box[2])/2,
                    center_y=(item.mosaic_box[1]+item.mosaic_box[3])/2, auto_state=state,
                    effective_state=state, version=1, created_at=utc_now()))
            run.stats_json = canonical_json(counts)
            WorkflowService(session).invalidate_from_inference(job.task_id)
            session.execute(update(Task).where(Task.id == job.task_id).values(version=Task.version + 1, updated_at=utc_now()))
            session.commit()
        return {"inference_run_id": run_id, "predictions_artifact_id": artifact_id, "review_crop_count": len(crop_specs), "stats": counts, "provider": snapshot["provider"], "demo": snapshot["provider"] == "fake"}

    def _progress(self, job_id: str, worker_id: str, value: int, step: str, message: str) -> None:
        with self.factory() as session:
            JobService(session, self.settings).report_progress(job_id, worker_id, progress=value, step=step, message=message)
