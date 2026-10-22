"""AI traces: one row per AI run (ai_runs) and one per step (ai_steps).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("answer", sa.JSON(), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index(op.f("ix_ai_runs_started_at"), "ai_runs", ["started_at"])
    op.create_table(
        "ai_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["ai_runs.id"], name=op.f("fk_ai_steps_run_id_ai_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_steps")),
        sa.UniqueConstraint("run_id", "position", name=op.f("uq_ai_steps_run_id")),
    )
    op.create_index(op.f("ix_ai_steps_run_id"), "ai_steps", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_steps_run_id"), table_name="ai_steps")
    op.drop_table("ai_steps")
    op.drop_index(op.f("ix_ai_runs_started_at"), table_name="ai_runs")
    op.drop_table("ai_runs")
