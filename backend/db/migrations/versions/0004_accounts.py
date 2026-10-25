"""Accounts (Phase 9): the users table, solves per account, and AI runs per visitor.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    # Existing rows keep NULL: solves made before accounts belong to no account.
    with op.batch_alter_table("solves") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_index(batch.f("ix_solves_user_id"), ["user_id"])
        batch.create_foreign_key(
            batch.f("fk_solves_user_id_users"), "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
    with op.batch_alter_table("ai_runs") as batch:
        batch.add_column(sa.Column("owner", sa.String(length=40), nullable=True))
        batch.create_index(batch.f("ix_ai_runs_owner"), ["owner"])


def downgrade() -> None:
    with op.batch_alter_table("ai_runs") as batch:
        batch.drop_index(batch.f("ix_ai_runs_owner"))
        batch.drop_column("owner")
    with op.batch_alter_table("solves") as batch:
        batch.drop_constraint(batch.f("fk_solves_user_id_users"), type_="foreignkey")
        batch.drop_index(batch.f("ix_solves_user_id"))
        batch.drop_column("user_id")
    op.drop_table("users")
