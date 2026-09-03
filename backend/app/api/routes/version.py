from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.core.config import Settings
from app.core.db import get_schema_revision
from app.domain.schemas import ProviderSummary, VersionResponse
from app.adapters.detection.ultralytics import installed_ultralytics_version
from app.adapters.mosaic.opencv import opencv_runtime_available


router = APIRouter(tags=["system"])


@router.get("/version", response_model=VersionResponse)
def version(request: Request) -> VersionResponse:
    settings: Settings = request.app.state.settings
    return VersionResponse(
        application="MosquitoMapper Backend",
        version=__version__,
        schema_revision=get_schema_revision(request.app.state.engine),
        commit=settings.app_commit or None,
        environment=settings.app_env,
        providers={
            "mosaic": ProviderSummary(
                name=settings.mosaic_provider,
                configured=(
                    settings.mosaic_provider == "fake" and not settings.production_mode
                )
                or (
                    settings.mosaic_provider == "opencv"
                    and opencv_runtime_available()
                ),
            ),
            "detector": ProviderSummary(
                name=settings.detector_provider,
                configured=(
                    settings.detector_provider == "fake" and not settings.production_mode
                )
                or bool(
                    settings.model_weights_path
                    and settings.model_weights_path.expanduser().is_file()
                    and installed_ultralytics_version() is not None
                    and (
                        not settings.model_required_ultralytics_version
                        or installed_ultralytics_version()
                        == settings.model_required_ultralytics_version
                    )
                ),
            ),
            "decision": ProviderSummary(
                name=settings.decision_provider,
                configured=settings.decision_provider == "rules"
                or bool(
                    settings.openai_base_url
                    and settings.openai_api_key
                    and settings.openai_model
                ),
            ),
        },
        limits={
            "max_upload_files": settings.max_upload_files,
            "max_upload_file_bytes": settings.max_upload_file_bytes,
            "max_task_bytes": settings.max_task_bytes,
        },
    )
