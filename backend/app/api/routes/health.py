from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.core.db import check_database_writable, get_worker_last_seen_at
from app.domain.schemas import LiveResponse, ReadyResponse
from app.adapters.detection.ultralytics import installed_ultralytics_version
from app.adapters.mosaic.opencv import opencv_runtime_available


router = APIRouter(prefix="/health", tags=["health"])


def _check_storage_writable(storage_root: Path) -> None:
    storage_root.mkdir(parents=True, exist_ok=True)
    probe = storage_root / f".ready-{uuid4().hex}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"ready")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        probe.unlink(missing_ok=True)


def _provider_checks(settings: Settings) -> tuple[dict[str, object], bool]:
    mosaic_configured = True
    if settings.mosaic_provider == "fake":
        mosaic_configured = not settings.production_mode
    elif settings.mosaic_provider == "opencv":
        mosaic_configured = opencv_runtime_available()

    detector_configured = True
    if settings.detector_provider == "fake":
        detector_configured = not settings.production_mode
    elif settings.detector_provider in {"yolov13", "yolo11"}:
        runtime_version = installed_ultralytics_version()
        detector_configured = bool(
            settings.model_weights_path
            and settings.model_weights_path.expanduser().is_file()
            and runtime_version is not None
            and (
                not settings.model_required_ultralytics_version
                or runtime_version == settings.model_required_ultralytics_version
            )
        )

    decision_configured = True
    if settings.decision_provider == "openai_compatible":
        decision_configured = bool(
            settings.openai_base_url
            and settings.openai_api_key
            and settings.openai_model
        )

    checks: dict[str, object] = {
        "mosaic_provider": {
            "name": settings.mosaic_provider,
            "configured": mosaic_configured,
            "strategy": (
                "opencv_scans_affine"
                if settings.mosaic_provider == "opencv"
                else "deterministic_demo_montage"
            ),
        },
        "detector_provider": {
            "name": settings.detector_provider,
            "configured": detector_configured,
            "runtime_version": (
                installed_ultralytics_version()
                if settings.detector_provider in {"yolov13", "yolo11"}
                else None
            ),
        },
        "decision_provider": {
            "name": settings.decision_provider,
            "configured": decision_configured,
        },
    }
    providers_ready = mosaic_configured and detector_configured and decision_configured
    return checks, providers_ready


@router.get("/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
def ready(request: Request) -> ReadyResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    engine = request.app.state.engine
    checks: dict[str, object] = {}
    ready_state = True

    try:
        check_database_writable(engine)
        checks["database"] = "ok"
    except Exception as exc:  # readiness must report, not raise
        checks["database"] = {"status": "error", "detail": type(exc).__name__}
        ready_state = False

    try:
        _check_storage_writable(settings.resolved_storage_root)
        checks["storage"] = "ok"
    except Exception as exc:  # readiness must report, not raise
        checks["storage"] = {"status": "error", "detail": type(exc).__name__}
        ready_state = False

    provider_checks, providers_ready = _provider_checks(settings)
    checks.update(provider_checks)
    if settings.production_mode and not providers_ready:
        ready_state = False

    worker_last_seen = get_worker_last_seen_at(engine)
    checks["worker_last_seen_at"] = (
        worker_last_seen.isoformat().replace("+00:00", "Z")
        if worker_last_seen
        else None
    )

    payload = ReadyResponse(
        status="ready" if ready_state else "not_ready",
        checks=checks,
    )
    if not ready_state:
        return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))
    return payload
