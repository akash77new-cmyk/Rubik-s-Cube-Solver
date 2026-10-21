"""The database connection: engine, transactions and a status report for the UI.

* ``Database(url)`` builds a SQLAlchemy engine with settings that suit each backend:
  SQLite on your laptop and in tests, PostgreSQL (Neon) in production.
* ``transaction(what)`` is how every store reads and writes: one short transaction,
  committed when the block ends, rolled back if it fails. A database error comes out
  as a :class:`StorageError` with a plain-English message, e.g.
  "Could not save settings: connection refused".
* ``status()`` never touches the network, so every state snapshot can include it.
  ``check()`` asks the server and refreshes it.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator

from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class StorageError(RuntimeError):
    """A database operation failed. The message is safe to show to the user."""


def short_error(exc: BaseException) -> str:
    """First line of the driver's error: readable, and never the connection URL."""
    original = getattr(exc, "orig", None) or exc
    lines = str(original).strip().splitlines()
    return (lines[0] if lines else type(original).__name__)[:200]


def public_host(host: str) -> str:
    """The host as users may see it. A Neon endpoint id (the first part of the host) is
    what you need to connect, and the live site is public, so it is hidden:
    ``ep-cool-name-123.ap-southeast-1.aws.neon.tech`` -> ``***.ap-southeast-1.aws.neon.tech``."""
    if host.endswith(".neon.tech"):
        return "***" + host[host.index("."):]
    return host


def describe_location(url: URL) -> str:
    """Where the data lives, without the user name, password or Neon endpoint id."""
    if url.get_backend_name() == "sqlite":
        if url.database in (None, "", ":memory:"):
            return "in memory (tests only)"
        path = Path(url.database).resolve()
        try:
            return path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return path.as_posix()
    return f"{public_host(url.host or '')}/{url.database}"


def _engine_options(url: URL) -> Dict[str, Any]:
    if url.get_backend_name() == "sqlite":
        if url.database in (None, "", ":memory:"):
            # Tests: one in-memory database shared by every thread.
            return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        # Wait up to 15 s for a lock held by another process instead of failing at once.
        return {"connect_args": {"timeout": 15}}
    return {
        # A few connections are plenty: one engine process, a handful of threads.
        "pool_size": 2,
        "max_overflow": 3,
        # Neon's free compute sleeps after 5 idle minutes and drops its connections.
        # Test each pooled connection before use, and replace any older than 5 minutes.
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "connect_args": {
            "connect_timeout": 10,
            "application_name": "rubiks-cube-solver",
            # Don't create server-side prepared statements: they break behind a
            # connection pooler (in case someone uses Neon's "-pooler" address).
            "prepare_threshold": None,
        },
    }


class Database:
    """Owns the SQLAlchemy engine and knows how healthy the connection is."""

    def __init__(self, url: str) -> None:
        self.url: URL = make_url(url)
        #: "postgresql" or "sqlite"
        self.dialect = self.url.get_backend_name()
        self.engine = create_engine(self.url, **_engine_options(self.url))
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._lock = threading.Lock()
        host = self.url.host or ""
        self._status: Dict[str, Any] = {
            "backend": "PostgreSQL" if self.dialect == "postgresql" else "SQLite",
            "provider": "Neon" if host.endswith(".neon.tech") else None,
            "location": describe_location(self.url),
            "connected": None,  # None = not checked yet
            "error": None,
            "serverVersion": None,
            "schemaRevision": None,
            "pgvector": None,  # pgvector version the server offers (Phase 7 uses it)
            "checkedAt": None,
        }

    # ------------------------------------------------------------------
    @contextmanager
    def transaction(self, what: str) -> Iterator[Session]:
        """``with db.transaction("save settings") as session:`` - commit, or roll back on error."""
        try:
            with self._sessions.begin() as session:
                yield session
        except SQLAlchemyError as exc:
            self._update_status(connected=False, error=self.public_error(exc))
            raise StorageError(f"Could not {what}: {self.public_error(exc)}") from exc
        self._update_status(connected=True, error=None)

    def check(self) -> Dict[str, Any]:
        """Ask the server for its version and our schema version (a few quick queries)."""
        try:
            with self.engine.connect() as connection:
                if self.dialect == "postgresql":
                    version = connection.execute(text("SHOW server_version")).scalar()
                    pgvector = connection.execute(
                        text("SELECT default_version FROM pg_available_extensions WHERE name = 'vector'")
                    ).scalar()
                else:
                    version = connection.execute(text("SELECT sqlite_version()")).scalar()
                    pgvector = None
                revision = MigrationContext.configure(connection).get_current_revision()
        except SQLAlchemyError as exc:
            self._update_status(connected=False, error=self.public_error(exc), checkedAt=time.time())
        else:
            self._update_status(
                connected=True,
                error=None,
                serverVersion=str(version).split()[0],
                schemaRevision=revision,
                pgvector=pgvector,
                checkedAt=time.time(),
            )
        return self.status()

    def public_error(self, exc: BaseException) -> str:
        """``short_error``, with the host hidden the same way as in ``status()``."""
        message = short_error(exc)
        host = self.url.host
        return message.replace(host, public_host(host)) if host else message

    def status(self) -> Dict[str, Any]:
        """The last known status. No I/O, so it is safe in every state snapshot."""
        with self._lock:
            return dict(self._status)

    def dispose(self) -> None:
        """Close every pooled connection (at shutdown, and in tests)."""
        self.engine.dispose()

    # ------------------------------------------------------------------
    def _update_status(self, **changes: Any) -> None:
        with self._lock:
            self._status.update(changes)
