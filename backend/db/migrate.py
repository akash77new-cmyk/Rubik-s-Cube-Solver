"""Schema migrations with Alembic.

A migration is a small script that changes the database schema one step, e.g.
"create the solves table". Alembic records the last step applied in a table called
``alembic_version``, so ``upgrade`` only runs the steps a database hasn't had yet.

The vision engine calls :func:`upgrade_with_retry` at start-up, so a new deploy
updates the schema by itself. The ``alembic`` command (see ``alembic.ini``) runs the
same migrations by hand, and creates new ones.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import OperationalError

from backend.db.database import Database, StorageError

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config() -> Config:
    """Alembic settings in code, so the app needs no alembic.ini."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def head_revision() -> str:
    """The newest migration in the code, e.g. ``"0001"``."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert head is not None, "no migrations found"
    return head


def upgrade(database: Database, revision: str = "head") -> None:
    """Apply every migration the database hasn't had yet (on the app's own engine)."""
    config = alembic_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(database: Database, revision: str) -> None:
    """Undo migrations down to ``revision`` ("base" = an empty database). Tests use it."""
    config = alembic_config()
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def upgrade_with_retry(
    database: Database,
    attempts: int = 5,
    delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """:func:`upgrade`, retried while the server can't be reached.

    Neon's free compute sleeps after 5 idle minutes. Waking it usually takes under a
    second, but the very first connection after a long sleep can fail.
    """
    for attempt in range(1, attempts + 1):
        try:
            upgrade(database)
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise StorageError(
                    f"Could not reach the database after {attempts} attempts: "
                    f"{database.public_error(exc)}"
                ) from exc
            log.warning(
                "Database not reachable (attempt %d of %d): %s - retrying in %.0f s",
                attempt, attempts, database.public_error(exc), delay,
            )
            sleep(delay)
