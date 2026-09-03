"""Rename hotspot fields to the target-clustering metric terminology.

Revision ID: 20260824_0007
Revises: 20260813_0006
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260824_0007"
down_revision: str | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hotspots") as batch_op:
        batch_op.alter_column(
            "score",
            new_column_name="clustering_index",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "risk_level",
            new_column_name="clustering_level",
            existing_type=sa.String(length=20),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("hotspots") as batch_op:
        batch_op.alter_column(
            "clustering_level",
            new_column_name="risk_level",
            existing_type=sa.String(length=20),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "clustering_index",
            new_column_name="score",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
