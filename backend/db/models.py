"""Database tables, as SQLAlchemy ORM classes.

Phase 3's three tables replaced the JSON files used before; Phases 4 and 7 added three:

========================  =====================================================
``app_settings``          the Settings page (one row, all settings as JSON)
``color_profiles``        HSV profiles saved on the Calibration page
``solves``                solve history behind the Analytics page
``ai_runs``, ``ai_steps``  traces of AI runs (Phase 4): see backend/ai/tracing.py
``lesson_embeddings``     the RAG coach's lesson embeddings (Phase 7): see backend/ai/retrieval.py
========================  =====================================================

Built-in HSV presets stay in code (``backend/core/color.py``): they are part of the
program, not user data.

Changing a table means changing a class here **and** adding an Alembic migration
(``backend/db/migrations/versions/``). A test fails if the two ever disagree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import base as postgresql_base
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """A timestamp that always comes back as a timezone-aware UTC datetime.

    Postgres stores ``timestamp with time zone`` properly. SQLite has no date type:
    it stores text and returns a datetime without a timezone. This type adds UTC
    back, so the app sees the same thing on both databases.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (use UTC)")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:  # SQLite
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PGVector(UserDefinedType):
    """pgvector's column type, ``vector(n)``: n floats the database can compare."""

    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: Any) -> str:
        return f"vector({self.dimensions})"


# Let SQLAlchemy recognise "vector" columns when it reads a Postgres schema (the test that
# compares models.py with the migrations does this).
postgresql_base.ischema_names["vector"] = PGVector


class Vector(TypeDecorator):
    """An embedding (a list of floats): ``vector(n)`` on Postgres, JSON elsewhere.

    On Postgres the database itself compares embeddings (``<=>`` is cosine distance),
    which is what the RAG coach's search uses. SQLite has no vector type, so there the
    list is stored as JSON and compared in Python.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGVector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Optional[List[float]], dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return "[" + ",".join(repr(float(x)) for x in value) + "]"  # pgvector's text format
        return [float(x) for x in value]

    def process_result_value(self, value: Any, dialect: Dialect) -> Optional[List[float]]:
        if value is None:
            return None
        if isinstance(value, str):  # "[0.1,0.2,...]" from Postgres
            return [float(x) for x in value.strip("[]").split(",") if x]
        return [float(x) for x in value]


class Base(DeclarativeBase):
    # Name every constraint and index explicitly. Migrations can then refer to them by
    # name, and the names are the same on SQLite and Postgres.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class SettingsRow(Base):
    """All Settings-page values in one JSON document.

    One row (id 1) for now; Phase 9 (accounts) adds one per user. JSON, not one
    column per setting: settings are always read and written together, and a new
    setting then needs no migration. ``Settings.from_dict`` fills in defaults for
    missing keys and ignores unknown ones.
    """

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    data: Mapped[Dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class ColorProfileRow(Base):
    """One user-saved HSV profile: a name plus six colour ranges."""

    __tablename__ = "color_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    #: {"W": {"h_min": 0, "h_max": 179, ...}, "Y": {...}, ...}
    ranges: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class SolveRow(Base):
    """One completed solve. Columns match ``SolveRecord`` in services/analytics.py."""

    __tablename__ = "solves"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    #: Indexed: history is always read in the order the solves finished.
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    move_count: Mapped[int] = mapped_column(Integer)
    quarter_turns: Mapped[int] = mapped_column(Integer)
    solve_ms: Mapped[float] = mapped_column(Float)
    scan_seconds: Mapped[float] = mapped_column(Float)
    execution_seconds: Mapped[float] = mapped_column(Float)
    backend: Mapped[str] = mapped_column(String(64))
    notation: Mapped[str] = mapped_column(Text)
    face_distribution: Mapped[Dict[str, int]] = mapped_column(JSON)
    turn_distribution: Mapped[Dict[str, int]] = mapped_column(JSON)
    detection_confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))


class AIRunRow(Base):
    """One AI run: the question, where the answer came from, and totals."""

    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    feature: Mapped[str] = mapped_column(String(32))  # e.g. "assistant"
    question: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # "gemini" or "fallback"
    reason: Mapped[Optional[str]] = mapped_column(Text)  # why the fallback was used
    model: Mapped[Optional[str]] = mapped_column(String(64))
    answer: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    request_count: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    #: Indexed: the AI page lists the newest runs first.
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    duration_ms: Mapped[int] = mapped_column(Integer)


class AIStepRow(Base):
    """One step of a run: a model request, a tool call, the answer, or an error."""

    __tablename__ = "ai_steps"
    __table_args__ = (UniqueConstraint("run_id", "position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("ai_runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)  # 1, 2, 3 ... within the run
    kind: Mapped[str] = mapped_column(String(16))  # "model", "tool", "answer" or "error"
    name: Mapped[str] = mapped_column(String(64))  # model name or tool name
    detail: Mapped[Dict[str, Any]] = mapped_column(JSON)
    duration_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class LessonEmbeddingRow(Base):
    """The embedding of one lesson section (a chunk), for the RAG coach (Phase 7).

    The lessons themselves are files in backend/lessons/. A row is only valid while
    the chunk's text (``content_hash``) and the embedding model are unchanged; the
    index re-embeds anything else at start-up.
    """

    __tablename__ = "lesson_embeddings"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)  # the chunk id
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the embedded text
    model: Mapped[str] = mapped_column(String(64))  # e.g. "gemini-embedding-001"
    embedding: Mapped[List[float]] = mapped_column(Vector(768))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
