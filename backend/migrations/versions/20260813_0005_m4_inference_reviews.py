"""M4 model versions, inference runs, detections, and reviews.

Revision ID: 20260813_0005
Revises: 20260813_0004
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260813_0005"
down_revision: str | None = "20260813_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("weights_sha256", sa.String(64), nullable=False),
        sa.Column("weights_label", sa.String(255), nullable=False),
        sa.Column("input_size", sa.Integer(), nullable=False),
        sa.Column("class_map_json", sa.Text(), nullable=False),
        sa.Column("device", sa.String(80), nullable=False),
        sa.Column("code_version", sa.String(80), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "weights_sha256", "code_version", name="uq_model_versions_identity"),
    )
    op.create_index("ix_model_versions_provider_active", "model_versions", ["provider", "active"])
    op.create_index(
        "uq_model_versions_one_active_provider", "model_versions", ["provider"],
        unique=True, sqlite_where=sa.text("active = 1"),
    )

    op.create_table(
        "inference_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("grid_plan_id", sa.String(36), nullable=False),
        sa.Column("model_version_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("predictions_artifact_id", sa.String(36), nullable=True),
        sa.Column("thresholds_json", sa.Text(), nullable=False),
        sa.Column("nms_iou", sa.Float(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("review_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["grid_plan_id"], ["grid_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predictions_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_inference_runs_task_status", "inference_runs", ["task_id", "status"])
    op.create_index("ix_inference_runs_grid_plan", "inference_runs", ["grid_plan_id"])
    op.create_index(
        "uq_inference_runs_one_current", "inference_runs", ["task_id"],
        unique=True, sqlite_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "detections",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("inference_run_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("class_id", sa.Integer(), nullable=False),
        sa.Column("class_name", sa.String(120), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_grid_tile_id", sa.String(36), nullable=False),
        sa.Column("crop_artifact_id", sa.String(36), nullable=True),
        sa.Column("tile_box_json", sa.Text(), nullable=False),
        sa.Column("mosaic_box_json", sa.Text(), nullable=False),
        sa.Column("center_x", sa.Float(), nullable=False),
        sa.Column("center_y", sa.Float(), nullable=False),
        sa.Column("auto_state", sa.String(20), nullable=False),
        sa.Column("effective_state", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["inference_run_id"], ["inference_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_grid_tile_id"], ["grid_tiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["crop_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inference_run_id", "code", name="uq_detections_run_code"),
    )
    op.create_index("ix_detections_run_state_conf", "detections", ["inference_run_id", "effective_state", "confidence"])
    op.create_index("ix_detections_run_class", "detections", ["inference_run_id", "class_name"])

    op.create_table(
        "review_actions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("detection_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("previous_effective_state", sa.String(20), nullable=False),
        sa.Column("new_effective_state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["detection_id"], ["detections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_actions_detection_created", "review_actions", ["detection_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_review_actions_detection_created", table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_index("ix_detections_run_class", table_name="detections")
    op.drop_index("ix_detections_run_state_conf", table_name="detections")
    op.drop_table("detections")
    op.drop_index("uq_inference_runs_one_current", table_name="inference_runs")
    op.drop_index("ix_inference_runs_grid_plan", table_name="inference_runs")
    op.drop_index("ix_inference_runs_task_status", table_name="inference_runs")
    op.drop_table("inference_runs")
    op.drop_index("uq_model_versions_one_active_provider", table_name="model_versions")
    op.drop_index("ix_model_versions_provider_active", table_name="model_versions")
    op.drop_table("model_versions")
