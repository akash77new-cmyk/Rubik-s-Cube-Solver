"""Lesson embeddings for the RAG coach (Phase 7): pgvector on Postgres when it is available.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


class Vector768(sa.types.UserDefinedType):
    """pgvector's vector(768), written here because migrations never import app code."""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "vector(768)"


def pgvector_ready(bind: Any) -> bool:
    """Turn pgvector on for this database if it may be (Neon allows it). Without it the
    embeddings are stored as JSON and compared in Python, so the app still works."""
    if bind.dialect.name != "postgresql":
        return False
    if bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).scalar():
        return True
    try:
        with bind.begin_nested():  # a savepoint: a refusal must not abort the whole upgrade
            bind.execute(sa.text("CREATE EXTENSION vector"))
        return True
    except sa.exc.DBAPIError:  # not installed on this server, or not allowed for this user
        return False


def upgrade() -> None:
    embedding: Any = Vector768() if pgvector_ready(op.get_bind()) else sa.JSON()
    op.create_table(
        "lesson_embeddings",
        sa.Column("id", sa.String(length=120), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding", embedding, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lesson_embeddings")),
    )


def downgrade() -> None:
    op.drop_table("lesson_embeddings")  # the vector extension stays: other data may use it
