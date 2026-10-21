"""Initial schema: settings, colour profiles and solve history.

Replaces the three JSON files in data/ used before Phase 3.

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
    )
    op.create_table(
        "color_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("ranges", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_color_profiles")),
        sa.UniqueConstraint("name", name=op.f("uq_color_profiles_name")),
    )
    op.create_table(
        "solves",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("move_count", sa.Integer(), nullable=False),
        sa.Column("quarter_turns", sa.Integer(), nullable=False),
        sa.Column("solve_ms", sa.Float(), nullable=False),
        sa.Column("scan_seconds", sa.Float(), nullable=False),
        sa.Column("execution_seconds", sa.Float(), nullable=False),
        sa.Column("backend", sa.String(length=64), nullable=False),
        sa.Column("notation", sa.Text(), nullable=False),
        sa.Column("face_distribution", sa.JSON(), nullable=False),
        sa.Column("turn_distribution", sa.JSON(), nullable=False),
        sa.Column("detection_confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solves")),
    )
    op.create_index(op.f("ix_solves_finished_at"), "solves", ["finished_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_solves_finished_at"), table_name="solves")
    op.drop_table("solves")
    op.drop_table("color_profiles")
    op.drop_table("app_settings")
