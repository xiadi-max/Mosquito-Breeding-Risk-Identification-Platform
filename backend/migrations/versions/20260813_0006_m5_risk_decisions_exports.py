"""M5 risk, decisions, and exports.

Revision ID: 20260813_0006
Revises: 20260813_0005
Create Date: 2026-08-13
"""

from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260813_0006"
down_revision: str | None = "20260813_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("inference_run_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("density_artifact_id", sa.String(36), nullable=True),
        sa.Column("review_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("bandwidth_px", sa.Float(), nullable=False),
        sa.Column("resolution_px", sa.Integer(), nullable=False),
        sa.Column("medium_threshold", sa.Integer(), nullable=False),
        sa.Column("high_threshold", sa.Integer(), nullable=False),
        sa.Column("accepted_detection_count", sa.Integer(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stats_json", sa.Text(), nullable=False),
        sa.Column("algorithm_version", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inference_run_id"], ["inference_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["density_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_risk_runs_task_status", "risk_runs", ["task_id", "status"])
    op.create_index("uq_risk_runs_one_current", "risk_runs", ["task_id"], unique=True, sqlite_where=sa.text("status = 'current'"))

    op.create_table(
        "hotspots",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("risk_run_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(20), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False), sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False), sa.Column("dominant_category", sa.String(120)),
        sa.Column("polygon_pixel_json", sa.Text(), nullable=False), sa.Column("centroid_x", sa.Float(), nullable=False),
        sa.Column("centroid_y", sa.Float(), nullable=False), sa.Column("geometry_wgs84_json", sa.Text()),
        sa.Column("area_px2", sa.Float(), nullable=False), sa.Column("area_m2", sa.Float()),
        sa.ForeignKeyConstraint(["risk_run_id"], ["risk_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("risk_run_id", "code", name="uq_hotspots_run_code"),
    )

    op.create_table(
        "decision_versions",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("risk_run_id", sa.String(36), nullable=False), sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False), sa.Column("parent_version_id", sa.String(36)),
        sa.Column("provider", sa.String(50), nullable=False), sa.Column("model", sa.String(120)),
        sa.Column("context_text", sa.Text()), sa.Column("content_json", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot_json", sa.Text(), nullable=False), sa.Column("prompt_template_version", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["risk_run_id"], ["risk_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["decision_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("task_id", "version", name="uq_decision_versions_task_version"),
    )
    op.create_index("ix_decision_versions_task_status", "decision_versions", ["task_id", "status"])
    op.create_index("uq_decision_versions_one_current", "decision_versions", ["task_id"], unique=True, sqlite_where=sa.text("status = 'current'"))

    op.create_table(
        "exports",
        sa.Column("id", sa.String(36), nullable=False), sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False), sa.Column("format", sa.String(10), nullable=False),
        sa.Column("risk_run_id", sa.String(36), nullable=False), sa.Column("decision_version_id", sa.String(36)),
        sa.Column("artifact_id", sa.String(36)), sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["risk_run_id"], ["risk_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_version_id"], ["decision_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("job_id"),
    )
    op.create_index("ix_exports_task_created", "exports", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_exports_task_created", table_name="exports"); op.drop_table("exports")
    op.drop_index("uq_decision_versions_one_current", table_name="decision_versions")
    op.drop_index("ix_decision_versions_task_status", table_name="decision_versions"); op.drop_table("decision_versions")
    op.drop_table("hotspots")
    op.drop_index("uq_risk_runs_one_current", table_name="risk_runs")
    op.drop_index("ix_risk_runs_task_status", table_name="risk_runs"); op.drop_table("risk_runs")
