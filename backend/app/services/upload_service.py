from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image as PILImage
from PIL import UnidentifiedImageError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import resolve_storage_path
from app.core.time import ensure_utc, utc_now
from app.domain.enums import ArtifactKind, TaskState
from app.domain.image_schemas import (
    DuplicateImage,
    GPSInfo,
    ImageRead,
    ImageSummary,
    ImageUploadResponse,
    RejectedImage,
)
from app.domain.models import Artifact, Image, Task
from app.repositories.image_repository import ImageRepository
from app.repositories.job_repository import JobRepository
from app.services.task_service import TaskService
from app.services.workflow_service import WorkflowService


CHUNK_SIZE = 1024 * 1024
logger = logging.getLogger(__name__)
FORMAT_INFO = {
    "JPEG": ("image/jpeg", ".jpg"),
    # Some cameras and DJI workflows store a primary JPEG plus auxiliary
    # frames in an MPO container while keeping the .jpg extension. Pillow
    # reports these files as MPO, but their required magic signature and
    # primary frame are still JPEG-compatible.
    "MPO": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
}


class UploadRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(slots=True)
class ImageInspection:
    mime_type: str
    extension: str
    width: int
    height: int
    captured_at: datetime | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    gps_alt_m: float | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    warnings: list[str] = field(default_factory=list)


def _safe_display_name(filename: str | None) -> str:
    value = (filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    value = "".join(character for character in value if ord(character) >= 32).strip()
    return (value or "upload")[:255]


def _magic_mime(path: Path) -> str | None:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    return None


def _as_float(value: Any) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator)
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / float(value[1])
    return float(value)


def _gps_coordinate(values: Any, reference: Any) -> float:
    degrees = _as_float(values[0])
    minutes = _as_float(values[1])
    seconds = _as_float(values[2])
    result = degrees + minutes / 60 + seconds / 3600
    ref = reference.decode("ascii", errors="ignore") if isinstance(reference, bytes) else str(reference)
    if ref.upper() in {"S", "W"}:
        result = -result
    return result


def _parse_exif_datetime(exif: Any, inspection: ImageInspection) -> None:
    raw = exif.get(36867) or exif.get(306)
    if not raw:
        return
    try:
        parsed = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        offset_value = exif.get(36881)
        if offset_value and re.fullmatch(r"[+-]\d{2}:\d{2}", str(offset_value)):
            sign = 1 if str(offset_value)[0] == "+" else -1
            hours, minutes = (int(part) for part in str(offset_value)[1:].split(":"))
            parsed = parsed.replace(
                tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes))
            )
            inspection.captured_at = parsed.astimezone(UTC)
        else:
            inspection.captured_at = parsed.replace(tzinfo=UTC)
            inspection.warnings.append("EXIF_TIMEZONE_MISSING_ASSUMED_UTC")
    except (TypeError, ValueError):
        inspection.warnings.append("EXIF_CAPTURE_TIME_INVALID")


def _parse_exif(image: PILImage.Image, inspection: ImageInspection) -> None:
    try:
        exif = image.getexif()
        if not exif:
            return
        inspection.camera_make = str(exif.get(271)).strip()[:120] if exif.get(271) else None
        inspection.camera_model = str(exif.get(272)).strip()[:120] if exif.get(272) else None
        _parse_exif_datetime(exif, inspection)
        try:
            gps = exif.get_ifd(34853)
        except (AttributeError, KeyError, TypeError, ValueError):
            gps = None
        if gps:
            try:
                inspection.gps_lat = _gps_coordinate(gps[2], gps[1])
                inspection.gps_lon = _gps_coordinate(gps[4], gps[3])
                if 6 in gps:
                    altitude = _as_float(gps[6])
                    inspection.gps_alt_m = -altitude if gps.get(5) == 1 else altitude
            except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
                inspection.warnings.append("EXIF_GPS_INVALID")
    except Exception:
        inspection.warnings.append("EXIF_PARSE_FAILED")


def inspect_image(path: Path, settings: Settings) -> ImageInspection:
    magic_mime = _magic_mime(path)
    if magic_mime is None:
        raise UploadRejected(
            "UNSUPPORTED_MEDIA_TYPE",
            "文件签名不是受支持的 JPEG 或 PNG。",
        )
    try:
        with warnings.catch_warnings():
            # Enforce the configured limit below instead of Pillow's global default.
            warnings.simplefilter("ignore", PILImage.DecompressionBombWarning)
            with PILImage.open(path) as image:
                image_format = image.format
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                    raise UploadRejected(
                        "IMAGE_DIMENSIONS_EXCEEDED",
                        "影像像素尺寸无效或超过服务器限制。",
                    )
                if image_format not in FORMAT_INFO:
                    raise UploadRejected(
                        "UNSUPPORTED_MEDIA_TYPE", "解码格式不是 JPEG 或 PNG。"
                    )
                mime_type, extension = FORMAT_INFO[image_format]
                if mime_type != magic_mime:
                    raise UploadRejected(
                        "UNSUPPORTED_MEDIA_TYPE", "文件签名与实际解码格式不一致。"
                    )
                image.load()
                inspection = ImageInspection(
                    mime_type=mime_type,
                    extension=extension,
                    width=width,
                    height=height,
                )
                _parse_exif(image, inspection)
                return inspection
    except UploadRejected:
        raise
    except PILImage.DecompressionBombError as exc:
        raise UploadRejected(
            "IMAGE_DIMENSIONS_EXCEEDED",
            "影像像素尺寸超过服务器限制。",
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UploadRejected(
            "UNSUPPORTED_MEDIA_TYPE", "文件无法作为安全、完整的影像解码。"
        ) from exc


def image_to_read(image: Image) -> ImageRead:
    try:
        warning_items = json.loads(image.warnings_json)
    except json.JSONDecodeError:
        warning_items = ["WARNINGS_METADATA_INVALID"]
    gps = None
    if image.gps_lat is not None and image.gps_lon is not None:
        gps = GPSInfo(
            latitude=image.gps_lat,
            longitude=image.gps_lon,
            altitude_m=image.gps_alt_m,
        )
    return ImageRead(
        id=image.id,
        artifact_id=image.artifact_id,
        display_name=image.display_name,
        size_bytes=image.size_bytes,
        mime_type=image.mime_type,
        sha256=image.sha256,
        width=image.width,
        height=image.height,
        captured_at=ensure_utc(image.captured_at) if image.captured_at else None,
        gps=gps,
        camera_make=image.camera_make,
        camera_model=image.camera_model,
        warnings=warning_items,
        created_at=ensure_utc(image.created_at),
    )


def build_image_summary(images: list[Image]) -> ImageSummary:
    captured = [ensure_utc(image.captured_at) for image in images if image.captured_at]
    capture_span = None
    if len(captured) >= 2:
        capture_span = int((max(captured) - min(captured)).total_seconds())
    return ImageSummary(
        image_count=len(images),
        total_size_bytes=sum(image.size_bytes for image in images),
        gps_count=sum(
            1 for image in images if image.gps_lat is not None and image.gps_lon is not None
        ),
        capture_span_seconds=capture_span,
    )


class UploadService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = ImageRepository(session)

    async def upload(self, task_id: str, files: list[UploadFile]) -> ImageUploadResponse:
        task = TaskService(self.session).get_model(task_id)
        if task.state != TaskState.RUNNING.value:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="当前任务不能上传影像",
                detail="只有处理中的任务可以新增影像。",
            )
        self._reject_while_mosaic_active(task_id)
        if not files:
            raise AppError(
                status_code=422,
                code="VALIDATION_ERROR",
                title="缺少影像文件",
                detail="files 至少包含一个上传文件。",
            )
        if len(files) > self.settings.max_upload_files:
            raise AppError(
                status_code=413,
                code="UPLOAD_LIMIT_EXCEEDED",
                title="上传文件数量超限",
                detail=f"单批最多上传 {self.settings.max_upload_files} 张影像。",
            )

        accepted: list[ImageRead] = []
        duplicates: list[DuplicateImage] = []
        rejected: list[RejectedImage] = []
        current_task_bytes = self.repository.total_bytes(task_id)
        temp_directory = resolve_storage_path(
            self.settings.resolved_storage_root, f"tasks/{task_id}/tmp/uploads"
        )
        temp_directory.mkdir(parents=True, exist_ok=True)

        for upload in files:
            display_name = _safe_display_name(upload.filename)
            temp_path = temp_directory / f"{uuid4()}.part"
            final_path: Path | None = None
            try:
                size_bytes, sha256 = await self._stream_to_temp(upload, temp_path)
                if current_task_bytes + size_bytes > self.settings.max_task_bytes:
                    raise UploadRejected(
                        "UPLOAD_LIMIT_EXCEEDED", "上传后将超过该任务的存储总量限制。"
                    )
                inspection = inspect_image(temp_path, self.settings)
                duplicate = self.repository.get_by_sha256(task_id, sha256)
                if duplicate is not None:
                    duplicates.append(
                        DuplicateImage(
                            id=duplicate.id,
                            display_name=duplicate.display_name,
                            sha256=duplicate.sha256,
                        )
                    )
                    continue

                image_id = str(uuid4())
                artifact_id = str(uuid4())
                relative_path = (
                    f"tasks/{task_id}/originals/{image_id}{inspection.extension}"
                )
                final_path = resolve_storage_path(
                    self.settings.resolved_storage_root, relative_path
                )
                final_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temp_path, final_path)

                now = utc_now()
                artifact = Artifact(
                    id=artifact_id,
                    task_id=task_id,
                    kind=ArtifactKind.ORIGINAL_IMAGE.value,
                    relative_path=relative_path,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    mime_type=inspection.mime_type,
                    width=inspection.width,
                    height=inspection.height,
                    metadata_json=json.dumps(
                        {"source": "upload"}, separators=(",", ":")
                    ),
                    is_current=True,
                    created_at=now,
                )
                image = Image(
                    id=image_id,
                    task_id=task_id,
                    artifact_id=artifact_id,
                    display_name=display_name,
                    sha256=sha256,
                    mime_type=inspection.mime_type,
                    size_bytes=size_bytes,
                    width=inspection.width,
                    height=inspection.height,
                    captured_at=inspection.captured_at,
                    gps_lat=inspection.gps_lat,
                    gps_lon=inspection.gps_lon,
                    gps_alt_m=inspection.gps_alt_m,
                    camera_make=inspection.camera_make,
                    camera_model=inspection.camera_model,
                    warnings_json=json.dumps(inspection.warnings, ensure_ascii=False),
                    created_at=now,
                )
                self.session.add_all([artifact, image])
                self.session.commit()
                accepted.append(image_to_read(image))
                current_task_bytes += size_bytes
            except UploadRejected as exc:
                self.session.rollback()
                rejected.append(
                    RejectedImage(
                        display_name=display_name,
                        code=exc.code,
                        detail=exc.detail,
                    )
                )
            except Exception:
                self.session.rollback()
                if final_path is not None:
                    final_path.unlink(missing_ok=True)
                logger.exception(
                    "image upload failed",
                    extra={
                        "task_id": task_id,
                        "display_name": display_name,
                        "error_code": "UPLOAD_FAILED",
                    },
                )
                rejected.append(
                    RejectedImage(
                        display_name=display_name,
                        code="UPLOAD_FAILED",
                        detail="影像保存失败，请重试。",
                    )
                )
            finally:
                temp_path.unlink(missing_ok=True)
                await upload.close()

        if accepted:
            self._invalidate_mosaic(task_id)
            self.session.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(version=Task.version + 1, updated_at=utc_now())
            )
            self.session.commit()

        images = self.repository.list_for_task(task_id)
        return ImageUploadResponse(
            accepted=accepted,
            duplicates=duplicates,
            rejected=rejected,
            summary=build_image_summary(images),
        )

    async def _stream_to_temp(
        self, upload: UploadFile, temp_path: Path
    ) -> tuple[int, str]:
        digest = hashlib.sha256()
        size_bytes = 0
        with temp_path.open("xb") as destination:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > self.settings.max_upload_file_bytes:
                    raise UploadRejected(
                        "UPLOAD_LIMIT_EXCEEDED",
                        "单个文件大小超过服务器限制。",
                    )
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if size_bytes == 0:
            raise UploadRejected("UNSUPPORTED_MEDIA_TYPE", "不接受空文件。")
        return size_bytes, digest.hexdigest()

    def list(self, task_id: str):
        TaskService(self.session).get_model(task_id)
        images = self.repository.list_for_task(task_id)
        return [image_to_read(image) for image in images], build_image_summary(images)

    def delete(self, task_id: str, image_id: str) -> None:
        task = TaskService(self.session).get_model(task_id)
        if task.state != TaskState.RUNNING.value:
            raise AppError(
                status_code=400,
                code="INVALID_WORKFLOW_STATE",
                title="当前任务不能删除影像",
                detail="只有处理中的任务可以删除影像。",
            )
        self._reject_while_mosaic_active(task_id)
        image = self.repository.get_for_task(task_id, image_id)
        if image is None:
            raise AppError(
                status_code=404,
                code="IMAGE_NOT_FOUND",
                title="影像不存在",
                detail="未找到指定任务下的影像。",
            )
        artifact = image.artifact
        path = resolve_storage_path(
            self.settings.resolved_storage_root, artifact.relative_path
        )
        path.unlink(missing_ok=True)
        self.session.delete(image)
        self.session.flush()
        self.session.delete(artifact)
        self._invalidate_mosaic(task_id)
        self.session.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(version=Task.version + 1, updated_at=utc_now())
        )
        self.session.commit()

    def _reject_while_mosaic_active(self, task_id: str) -> None:
        active = JobRepository(self.session).active_for_type(task_id, "mosaic")
        if active:
            raise AppError(
                status_code=409,
                code="JOB_ALREADY_RUNNING",
                title="拼接作业正在执行",
                detail="请等待当前拼接作业结束或先取消，再修改输入影像。",
            )

    def _invalidate_mosaic(self, task_id: str) -> None:
        self.session.execute(
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
        WorkflowService(self.session).invalidate_from_images(task_id)
