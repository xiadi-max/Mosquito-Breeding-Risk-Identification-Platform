from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_commit: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = "sqlite:///./data/mosquito_mapper.sqlite3"
    storage_root: Path = Path("./data/artifacts")
    log_level: str = "INFO"
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"

    max_upload_files: int = Field(default=50, ge=1, le=1000)
    max_upload_file_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    max_task_bytes: int = Field(default=10 * 1024 * 1024 * 1024, ge=1)
    max_image_pixels: int = Field(default=100_000_000, ge=1)

    job_poll_interval: float = Field(default=1.0, gt=0, le=60)
    job_lease_seconds: int = Field(default=60, ge=15, le=3600)
    job_max_retries: int = Field(default=3, ge=1, le=100)
    mosaic_job_timeout_seconds: int = Field(default=14_400, ge=30, le=172_800)
    sse_heartbeat_seconds: int = Field(default=15, ge=5, le=60)

    mosaic_provider: Literal["fake", "opencv"] = "opencv"
    mosaic_work_scale: float = Field(default=0.6, gt=0, le=1)
    mosaic_pano_confidence_threshold: float = Field(default=0.3, ge=0, le=1)
    mosaic_black_border_threshold: int = Field(default=2, ge=0, le=255)
    mosaic_output_jpeg_quality: int = Field(default=95, ge=1, le=100)
    detector_provider: Literal["fake", "yolov13", "yolo11"] = "fake"
    model_weights_path: Path | None = None
    model_device: str = "cpu"
    model_input_size: int = Field(default=640, ge=320, le=4096)
    model_required_ultralytics_version: str | None = None
    infer_min_confidence: float = Field(default=0.20, ge=0, le=1)
    review_threshold: float = Field(default=0.50, ge=0, le=1)
    auto_accept_threshold: float = Field(default=0.80, ge=0, le=1)
    nms_iou: float = Field(default=0.45, gt=0, le=1)
    decision_provider: Literal["rules", "openai_compatible"] = "rules"
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    risk_medium_threshold: int = Field(default=40, ge=0, le=99)
    risk_high_threshold: int = Field(default=75, ge=1, le=100)
    backup_root: Path = Path("./backups")
    backup_retention_days: int = Field(default=14, ge=1, le=3650)

    @model_validator(mode="after")
    def validate_risk_threshold_order(self) -> "Settings":
        if self.risk_medium_threshold >= self.risk_high_threshold:
            raise ValueError("RISK_MEDIUM_THRESHOLD must be lower than RISK_HIGH_THRESHOLD")
        return self

    @model_validator(mode="after")
    def validate_inference_threshold_order(self) -> "Settings":
        if not (
            self.infer_min_confidence
            <= self.review_threshold
            <= self.auto_accept_threshold
        ):
            raise ValueError(
                "INFER_MIN_CONFIDENCE <= REVIEW_THRESHOLD <= "
                "AUTO_ACCEPT_THRESHOLD is required"
            )
        return self

    @property
    def backend_root(self) -> Path:
        return BACKEND_ROOT

    @property
    def resolved_storage_root(self) -> Path:
        path = self.storage_root
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve()

    @property
    def resolved_backup_root(self) -> Path:
        path = self.backup_root
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path.resolve()

    @property
    def resolved_database_url(self) -> str:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            return self.database_url
        raw_path = self.database_url[len(prefix) :]
        if raw_path == ":memory:" or raw_path.startswith("file:"):
            return self.database_url
        path = Path(raw_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return f"sqlite:///{path.resolve().as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        value = self.cors_origins.strip()
        if not value:
            return []
        if value.startswith("["):
            parsed = json.loads(value)
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in value.split(",") if item.strip()]

    @property
    def production_mode(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
