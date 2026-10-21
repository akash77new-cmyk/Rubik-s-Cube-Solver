"""Database tables, as SQLAlchemy ORM classes.

Three tables replace the three JSON files used before Phase 3:

========================  =====================================================
``app_settings``          the Settings page (one row, all settings as JSON)
``color_profiles``        HSV profiles saved on the Calibration page
``solves``                solve history behind the Analytics page
========================  =====================================================

Built-in HSV presets stay in code (``backend/core/color.py``): they are part of the
program, not user data.

Changing a table means changing a class here **and** adding an Alembic migration
(``backend/db/migrations/versions/``). A test fails if the two ever disagree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Float, Integer, MetaData, String, Text
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


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
