"""How Alembic connects when it runs a migration.

Two ways in:

* **The app** (``backend/db/migrate.py``) passes its own open connection in
  ``config.attributes["connection"]``.
* **The ``alembic`` command** (``alembic upgrade head``, ``alembic revision
  --autogenerate``) has no connection, so one is opened from ``DATABASE_URL``,
  exactly as the app would (``backend/config.py``).
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from backend.db.models import Base, UTCDateTime

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None:  # the alembic command: logging from alembic.ini
    fileConfig(config.config_file_name)


def render_item(type_, obj, autogen_context):
    """Write our UTCDateTime as plain ``sa.DateTime(timezone=True)`` in new migration
    files, so migrations never import app code (it may change later; they must not)."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False  # everything else: Alembic's default


def run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        # SQLite can't ALTER most things; "batch" mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


def database_url() -> str:
    from backend.config import RUNTIME

    return RUNTIME.database_url


if context.is_offline_mode():
    # `alembic upgrade head --sql`: print the SQL instead of running it.
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connection = config.attributes.get("connection")
    if connection is not None:
        run_migrations(connection)
    else:
        engine = create_engine(database_url(), poolclass=NullPool)
        with engine.connect() as connection:
            run_migrations(connection)
