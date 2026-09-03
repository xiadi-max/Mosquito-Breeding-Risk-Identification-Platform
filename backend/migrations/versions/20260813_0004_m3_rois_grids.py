"""M3 ROI versions, grid plans, and grid tiles.

Revision ID: 20260813_0004
Revises: 20260811_0003
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260813_0004"
down_revision: str | None = "20260811_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roi_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("mosaic_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("coordinate_space", sa.String(length=40), nullable=False),
        sa.Column("source_width", sa.Integer(), nullable=False),
        sa.Column("source_height", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mosaic_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version", name="uq_roi_versions_task_version"),
    )
    op.create_index("ix_roi_versions_task_created", "roi_versions", ["task_id", "created_at"])
    op.create_index(
        "uq_roi_versions_one_current",
        "roi_versions",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "rois",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("roi_version_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
        sa.Column("polygon_json", sa.Text(), nullable=False),
        sa.Column("area_px2", sa.Float(), nullable=False),
        sa.Column("area_m2", sa.Float(), nullable=True),
        sa.Column("geometry_wgs84_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["roi_version_id"], ["roi_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("roi_version_id", "code", name="uq_rois_version_code"),
    )

    op.create_table(
        "grid_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("roi_version_id", sa.String(length=36), nullable=False),
        sa.Column("mosaic_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("tile_size", sa.Integer(), nullable=False),
        sa.Column("overlap", sa.Float(), nullable=False),
        sa.Column("step_px", sa.Integer(), nullable=False),
        sa.Column("edge_strategy", sa.String(length=20), nullable=False),
        sa.Column("min_roi_intersection", sa.Float(), nullable=False),
        sa.Column("tile_count", sa.Integer(), nullable=False),
        sa.Column("padded_count", sa.Integer(), nullable=False),
        sa.Column("estimated_bytes", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["mosaic_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["roi_version_id"], ["roi_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_grid_plans_task_status", "grid_plans", ["task_id", "status"])
    op.create_index("ix_grid_plans_roi_version", "grid_plans", ["roi_version_id"])
    op.create_index(
        "uq_grid_plans_one_current",
        "grid_plans",
        ["task_id"],
        unique=True,
        sqlite_where=sa.text("status = 'current'"),
    )

    op.create_table(
        "grid_tiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("grid_plan_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("source_x1", sa.Integer(), nullable=False),
        sa.Column("source_y1", sa.Integer(), nullable=False),
        sa.Column("source_x2", sa.Integer(), nullable=False),
        sa.Column("source_y2", sa.Integer(), nullable=False),
        sa.Column("pad_left", sa.Integer(), nullable=False),
        sa.Column("pad_top", sa.Integer(), nullable=False),
        sa.Column("pad_right", sa.Integer(), nullable=False),
        sa.Column("pad_bottom", sa.Integer(), nullable=False),
        sa.Column("tile_to_mosaic_json", sa.Text(), nullable=False),
        sa.Column("roi_intersection", sa.Float(), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["grid_plan_id"], ["grid_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grid_plan_id", "code", name="uq_grid_tiles_plan_code"),
    )
    op.create_index("ix_grid_tiles_plan", "grid_tiles", ["grid_plan_id"])


def downgrade() -> None:
    op.drop_index("ix_grid_tiles_plan", table_name="grid_tiles")
    op.drop_table("grid_tiles")
    op.drop_index("uq_grid_plans_one_current", table_name="grid_plans")
    op.drop_index("ix_grid_plans_roi_version", table_name="grid_plans")
    op.drop_index("ix_grid_plans_task_status", table_name="grid_plans")
    op.drop_table("grid_plans")
    op.drop_table("rois")
    op.drop_index("uq_roi_versions_one_current", table_name="roi_versions")
    op.drop_index("ix_roi_versions_task_created", table_name="roi_versions")
    op.drop_table("roi_versions")
