from __future__ import annotations

from datetime import datetime

from datetime import date

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Boolean,
    CheckConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_state_updated_at", "state", "updated_at"),
        Index("ix_tasks_survey_date", "survey_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    area: Mapped[str] = mapped_column(String(200), nullable=False)
    survey_date: Mapped[date] = mapped_column(Date, nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    images: Mapped[list["Image"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    roi_versions: Mapped[list["ROIVersion"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    grid_plans: Mapped[list["GridPlan"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    inference_runs: Mapped[list["InferenceRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    risk_runs: Mapped[list["RiskRun"]] = relationship(back_populates="task", cascade="all, delete-orphan", passive_deletes=True)
    decision_versions: Mapped[list["DecisionVersion"]] = relationship(back_populates="task", cascade="all, delete-orphan", passive_deletes=True)
    exports: Mapped[list["Export"]] = relationship(back_populates="task", cascade="all, delete-orphan", passive_deletes=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_task_kind", "task_id", "kind"),
        Index("ix_artifacts_job_id", "job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    crs: Mapped[str | None] = mapped_column(String(120))
    affine_json: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="artifacts")
    image: Mapped["Image | None"] = relationship(back_populates="artifact")


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("task_id", "sha256", name="uq_images_task_sha256"),
        UniqueConstraint("artifact_id", name="uq_images_artifact_id"),
        Index("ix_images_task_created_at", "task_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gps_lat: Mapped[float | None] = mapped_column(Float)
    gps_lon: Mapped[float | None] = mapped_column(Float)
    gps_alt_m: Mapped[float | None] = mapped_column(Float)
    camera_make: Mapped[str | None] = mapped_column(String(120))
    camera_model: Mapped[str | None] = mapped_column(String(120))
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    task: Mapped[Task] = relationship(back_populates="images")
    artifact: Mapped[Artifact] = relationship(back_populates="image")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress"),
        UniqueConstraint(
            "task_id", "type", "idempotency_key", name="uq_jobs_scope_idempotency"
        ),
        Index("ix_jobs_status_available", "status", "available_at", "created_at"),
        Index("ix_jobs_task_type_status", "task_id", "type", "status"),
        Index("ix_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[str] = mapped_column(String(80), nullable=False, default="queued")
    message: Mapped[str | None] = mapped_column(String(500))
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(120))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(String(1000))
    error_retryable: Mapped[bool | None] = mapped_column(Boolean)
    result_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship(back_populates="jobs")
    events: Mapped[list["JobEvent"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_job_id_id", "job_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    job: Mapped[Job] = relationship(back_populates="events")


class ROIVersion(Base):
    __tablename__ = "roi_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_roi_versions_task_version"),
        Index("ix_roi_versions_task_created", "task_id", "created_at"),
        Index(
            "uq_roi_versions_one_current",
            "task_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    mosaic_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    coordinate_space: Mapped[str] = mapped_column(
        String(40), nullable=False, default="mosaic_pixel"
    )
    source_width: Mapped[int] = mapped_column(Integer, nullable=False)
    source_height: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    task: Mapped[Task] = relationship(back_populates="roi_versions")
    mosaic_artifact: Mapped[Artifact] = relationship()
    rois: Mapped[list["ROI"]] = relationship(
        back_populates="roi_version", cascade="all, delete-orphan", passive_deletes=True
    )
    grid_plans: Mapped[list["GridPlan"]] = relationship(back_populates="roi_version")


class ROI(Base):
    __tablename__ = "rois"
    __table_args__ = (
        UniqueConstraint("roi_version_id", "code", name="uq_rois_version_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    roi_version_id: Mapped[str] = mapped_column(
        ForeignKey("roi_versions.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    polygon_json: Mapped[str] = mapped_column(Text, nullable=False)
    area_px2: Mapped[float] = mapped_column(Float, nullable=False)
    area_m2: Mapped[float | None] = mapped_column(Float)
    geometry_wgs84_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    roi_version: Mapped[ROIVersion] = relationship(back_populates="rois")


class GridPlan(Base):
    __tablename__ = "grid_plans"
    __table_args__ = (
        Index("ix_grid_plans_task_status", "task_id", "status"),
        Index("ix_grid_plans_roi_version", "roi_version_id"),
        Index(
            "uq_grid_plans_one_current",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'current'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    roi_version_id: Mapped[str] = mapped_column(
        ForeignKey("roi_versions.id", ondelete="RESTRICT"), nullable=False
    )
    mosaic_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    tile_size: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap: Mapped[float] = mapped_column(Float, nullable=False)
    step_px: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    min_roi_intersection: Mapped[float] = mapped_column(Float, nullable=False)
    tile_count: Mapped[int] = mapped_column(Integer, nullable=False)
    padded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    task: Mapped[Task] = relationship(back_populates="grid_plans")
    roi_version: Mapped[ROIVersion] = relationship(back_populates="grid_plans")
    mosaic_artifact: Mapped[Artifact] = relationship()
    job: Mapped[Job] = relationship()
    tiles: Mapped[list["GridTile"]] = relationship(
        back_populates="grid_plan", cascade="all, delete-orphan", passive_deletes=True
    )
    inference_runs: Mapped[list["InferenceRun"]] = relationship(
        back_populates="grid_plan"
    )


class GridTile(Base):
    __tablename__ = "grid_tiles"
    __table_args__ = (
        UniqueConstraint("grid_plan_id", "code", name="uq_grid_tiles_plan_code"),
        Index("ix_grid_tiles_plan", "grid_plan_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    grid_plan_id: Mapped[str] = mapped_column(
        ForeignKey("grid_plans.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    source_x1: Mapped[int] = mapped_column(Integer, nullable=False)
    source_y1: Mapped[int] = mapped_column(Integer, nullable=False)
    source_x2: Mapped[int] = mapped_column(Integer, nullable=False)
    source_y2: Mapped[int] = mapped_column(Integer, nullable=False)
    pad_left: Mapped[int] = mapped_column(Integer, nullable=False)
    pad_top: Mapped[int] = mapped_column(Integer, nullable=False)
    pad_right: Mapped[int] = mapped_column(Integer, nullable=False)
    pad_bottom: Mapped[int] = mapped_column(Integer, nullable=False)
    tile_to_mosaic_json: Mapped[str] = mapped_column(Text, nullable=False)
    roi_intersection: Mapped[float] = mapped_column(Float, nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )

    grid_plan: Mapped[GridPlan] = relationship(back_populates="tiles")
    artifact: Mapped[Artifact | None] = relationship()
    detections: Mapped[list["Detection"]] = relationship(back_populates="source_grid_tile")


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        Index("ix_model_versions_provider_active", "provider", "active"),
        UniqueConstraint(
            "provider", "weights_sha256", "code_version",
            name="uq_model_versions_identity",
        ),
        Index(
            "uq_model_versions_one_active_provider",
            "provider",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    weights_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    weights_label: Mapped[str] = mapped_column(String(255), nullable=False)
    input_size: Mapped[int] = mapped_column(Integer, nullable=False)
    class_map_json: Mapped[str] = mapped_column(Text, nullable=False)
    device: Mapped[str] = mapped_column(String(80), nullable=False)
    code_version: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    inference_runs: Mapped[list["InferenceRun"]] = relationship(
        back_populates="model_version"
    )


class InferenceRun(Base):
    __tablename__ = "inference_runs"
    __table_args__ = (
        Index("ix_inference_runs_task_status", "task_id", "status"),
        Index("ix_inference_runs_grid_plan", "grid_plan_id"),
        Index(
            "uq_inference_runs_one_current",
            "task_id",
            unique=True,
            sqlite_where=text("status = 'current'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    grid_plan_id: Mapped[str] = mapped_column(
        ForeignKey("grid_plans.id", ondelete="RESTRICT"), nullable=False
    )
    model_version_id: Mapped[str] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    predictions_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    thresholds_json: Mapped[str] = mapped_column(Text, nullable=False)
    nms_iou: Mapped[float] = mapped_column(Float, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    review_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    task: Mapped[Task] = relationship(back_populates="inference_runs")
    grid_plan: Mapped[GridPlan] = relationship(back_populates="inference_runs")
    model_version: Mapped[ModelVersion] = relationship(back_populates="inference_runs")
    job: Mapped[Job] = relationship()
    predictions_artifact: Mapped[Artifact | None] = relationship()
    detections: Mapped[list["Detection"]] = relationship(
        back_populates="inference_run", cascade="all, delete-orphan", passive_deletes=True
    )
    risk_runs: Mapped[list["RiskRun"]] = relationship(back_populates="inference_run")


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        UniqueConstraint("inference_run_id", "code", name="uq_detections_run_code"),
        Index("ix_detections_run_state_conf", "inference_run_id", "effective_state", "confidence"),
        Index("ix_detections_run_class", "inference_run_id", "class_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    inference_run_id: Mapped[str] = mapped_column(
        ForeignKey("inference_runs.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(120), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_grid_tile_id: Mapped[str] = mapped_column(
        ForeignKey("grid_tiles.id", ondelete="RESTRICT"), nullable=False
    )
    crop_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL")
    )
    tile_box_json: Mapped[str] = mapped_column(Text, nullable=False)
    mosaic_box_json: Mapped[str] = mapped_column(Text, nullable=False)
    center_x: Mapped[float] = mapped_column(Float, nullable=False)
    center_y: Mapped[float] = mapped_column(Float, nullable=False)
    auto_state: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_state: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    inference_run: Mapped[InferenceRun] = relationship(back_populates="detections")
    source_grid_tile: Mapped[GridTile] = relationship(back_populates="detections")
    crop_artifact: Mapped[Artifact | None] = relationship()
    review_actions: Mapped[list["ReviewAction"]] = relationship(
        back_populates="detection", cascade="all, delete-orphan", passive_deletes=True
    )


class ReviewAction(Base):
    __tablename__ = "review_actions"
    __table_args__ = (Index("ix_review_actions_detection_created", "detection_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    detection_id: Mapped[str] = mapped_column(
        ForeignKey("detections.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(String(500))
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    previous_effective_state: Mapped[str] = mapped_column(String(20), nullable=False)
    new_effective_state: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    detection: Mapped[Detection] = relationship(back_populates="review_actions")


class RiskRun(Base):
    __tablename__ = "risk_runs"
    __table_args__ = (
        Index("ix_risk_runs_task_status", "task_id", "status"),
        Index("uq_risk_runs_one_current", "task_id", unique=True, sqlite_where=text("status = 'current'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    inference_run_id: Mapped[str] = mapped_column(ForeignKey("inference_runs.id", ondelete="RESTRICT"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    density_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    review_snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    bandwidth_px: Mapped[float] = mapped_column(Float, nullable=False)
    resolution_px: Mapped[int] = mapped_column(Integer, nullable=False)
    medium_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    high_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_detection_count: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    algorithm_version: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    task: Mapped[Task] = relationship(back_populates="risk_runs")
    inference_run: Mapped[InferenceRun] = relationship(back_populates="risk_runs")
    job: Mapped[Job] = relationship()
    density_artifact: Mapped[Artifact | None] = relationship()
    hotspots: Mapped[list["Hotspot"]] = relationship(back_populates="risk_run", cascade="all, delete-orphan", passive_deletes=True)
    decisions: Mapped[list["DecisionVersion"]] = relationship(back_populates="risk_run")


class Hotspot(Base):
    __tablename__ = "hotspots"
    __table_args__ = (UniqueConstraint("risk_run_id", "code", name="uq_hotspots_run_code"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_run_id: Mapped[str] = mapped_column(ForeignKey("risk_runs.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    clustering_index: Mapped[int] = mapped_column(Integer, nullable=False)
    clustering_level: Mapped[str] = mapped_column(String(20), nullable=False)
    target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dominant_category: Mapped[str | None] = mapped_column(String(120))
    polygon_pixel_json: Mapped[str] = mapped_column(Text, nullable=False)
    centroid_x: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_y: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_wgs84_json: Mapped[str | None] = mapped_column(Text)
    area_px2: Mapped[float] = mapped_column(Float, nullable=False)
    area_m2: Mapped[float | None] = mapped_column(Float)
    risk_run: Mapped[RiskRun] = relationship(back_populates="hotspots")


class DecisionVersion(Base):
    __tablename__ = "decision_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_decision_versions_task_version"),
        Index("ix_decision_versions_task_status", "task_id", "status"),
        Index("uq_decision_versions_one_current", "task_id", unique=True, sqlite_where=text("status = 'current'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    risk_run_id: Mapped[str] = mapped_column(ForeignKey("risk_runs.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(ForeignKey("decision_versions.id", ondelete="RESTRICT"))
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    context_text: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    task: Mapped[Task] = relationship(back_populates="decision_versions")
    risk_run: Mapped[RiskRun] = relationship(back_populates="decisions")
    parent: Mapped["DecisionVersion | None"] = relationship(remote_side=[id])
    exports: Mapped[list["Export"]] = relationship(back_populates="decision_version")


class Export(Base):
    __tablename__ = "exports"
    __table_args__ = (Index("ix_exports_task_created", "task_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, unique=True)
    format: Mapped[str] = mapped_column(String(10), nullable=False)
    risk_run_id: Mapped[str] = mapped_column(ForeignKey("risk_runs.id", ondelete="RESTRICT"), nullable=False)
    decision_version_id: Mapped[str | None] = mapped_column(ForeignKey("decision_versions.id", ondelete="RESTRICT"))
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship(back_populates="exports")
    decision_version: Mapped[DecisionVersion | None] = relationship(back_populates="exports")
    risk_run: Mapped[RiskRun] = relationship()
    job: Mapped[Job] = relationship()
    artifact: Mapped[Artifact | None] = relationship()
