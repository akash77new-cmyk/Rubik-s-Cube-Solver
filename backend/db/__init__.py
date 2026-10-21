"""Database layer (Phase 3): connection, tables (models.py) and migrations (Alembic).

Only the vision engine and the command-line tools open the database. The web server
stays a pure relay and never imports this package.
"""

from __future__ import annotations

from typing import Optional

from backend.db.database import Database, StorageError
from backend.db.migrate import head_revision, upgrade_with_retry


def connect(url: Optional[str] = None, migrate: bool = True) -> Database:
    """Open the app's database, bring its schema up to date and check the connection.

    ``url`` defaults to ``DATABASE_URL`` (or the local SQLite file). Tests pass
    ``"sqlite://"`` for a fresh in-memory database.
    """
    if url is None:
        from backend.config import RUNTIME

        url = RUNTIME.database_url
    database = Database(url)
    if migrate:
        upgrade_with_retry(database)
    database.check()
    return database


__all__ = ["Database", "StorageError", "connect", "head_revision"]
