"""The database layer: connection status, transactions, timestamps, migrations.

Tests that take ``db_url`` or ``open_db`` run on SQLite, and on PostgreSQL too when
CUBE_TEST_POSTGRES_URL is set (see conftest.py).
"""

from datetime import datetime, timedelta, timezone

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select
from sqlalchemy.exc import OperationalError

from backend.config import normalize_database_url, read_runtime_config
from backend.db import Database, StorageError, connect, head_revision
from backend.db.migrate import downgrade, upgrade, upgrade_with_retry
from backend.db.models import Base, SettingsRow, SolveRow
from backend.services.analytics import SolveRecord

#: A connection string in the format Neon gives (made-up host and password).
NEON = (
    "postgresql://neondb_owner:s3cret@ep-cool-name-a1b2c3.ap-southeast-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
APP_TABLES = {"app_settings", "color_profiles", "solves", "ai_runs", "ai_steps", "lesson_embeddings", "users"}


# ----------------------------------------------------------------------------
# Connection and status
# ----------------------------------------------------------------------------
def test_status_never_shows_the_password_or_the_neon_endpoint():
    database = Database(normalize_database_url(NEON))  # no connection is made here
    status = database.status()
    assert status["backend"] == "PostgreSQL"
    assert status["provider"] == "Neon"
    assert status["location"] == "***.ap-southeast-1.aws.neon.tech/neondb"
    assert status["connected"] is None  # not checked yet
    assert "s3cret" not in str(status) and "ep-cool-name" not in str(status)


def test_error_messages_hide_the_neon_endpoint_too():
    database = Database(normalize_database_url(NEON))
    error = Exception('connection to server at "ep-cool-name-a1b2c3.ap-southeast-1.aws.neon.tech" failed')
    assert database.public_error(error) == (
        'connection to server at "***.ap-southeast-1.aws.neon.tech" failed'
    )


def test_check_reports_version_and_schema(open_db):
    database = open_db()
    status = database.status()
    assert status["connected"] is True and status["error"] is None
    assert status["schemaRevision"] == head_revision() == "0004"
    assert status["serverVersion"]
    if database.dialect == "sqlite":
        assert status["pgvector"] is None


def test_an_unreachable_server_is_a_storage_error_not_a_crash():
    # Port 1 on this machine: nothing listens there, so the connection is refused.
    database = Database("postgresql+psycopg://user:pw@127.0.0.1:1/cube")
    status = database.check()
    assert status["connected"] is False and status["error"]
    # Windows: psycopg misses the refusal and waits for connect_timeout instead.
    with pytest.raises(StorageError, match="Could not load settings: .*(refused|timeout expired)"):
        with database.transaction("load settings") as session:
            session.get(SettingsRow, 1)
    assert database.status()["connected"] is False


def test_a_failed_transaction_is_rolled_back(open_db):
    database = open_db()
    now = datetime.now(timezone.utc)
    row = dict(
        started_at=now, finished_at=now, move_count=1, quarter_turns=1, solve_ms=1.0,
        scan_seconds=1.0, execution_seconds=1.0, backend="t", notation="R",
        face_distribution={}, turn_distribution={}, detection_confidence=0.5, source="scan",
    )
    with database.transaction("add a solve") as session:
        session.add(SolveRow(id="a", **row))
    with pytest.raises(StorageError, match="Could not add two solves"):
        with database.transaction("add two solves") as session:
            session.add(SolveRow(id="b", **row))
            session.add(SolveRow(id="a", **row))  # duplicate primary key: the whole block fails
    with database.transaction("count") as session:
        assert set(session.scalars(select(SolveRow.id))) == {"a"}  # "b" was rolled back too


def test_timestamps_come_back_as_utc(open_db):
    database = open_db()
    local = datetime(2026, 10, 21, 18, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    row = SolveRow(
        id="t", started_at=local, finished_at=local, move_count=1, quarter_turns=1,
        solve_ms=1.0, scan_seconds=1.0, execution_seconds=1.0, backend="t", notation="R",
        face_distribution={}, turn_distribution={}, detection_confidence=0.5, source="scan",
    )
    with database.transaction("add") as session:
        session.add(row)
    with database.transaction("read") as session:
        stored = session.get(SolveRow, "t").finished_at
    assert stored == local and stored.utcoffset() == timedelta(0)  # 13:00 UTC, same instant


def test_naive_timestamps_are_refused(open_db):
    database = open_db()
    with pytest.raises(StorageError):
        with database.transaction("add") as session:
            session.add(SolveRow(
                id="n", started_at=datetime(2026, 1, 1), finished_at=datetime(2026, 1, 1),
                move_count=1, quarter_turns=1, solve_ms=1.0, scan_seconds=1.0,
                execution_seconds=1.0, backend="t", notation="R", face_distribution={},
                turn_distribution={}, detection_confidence=0.5, source="scan",
            ))


# ----------------------------------------------------------------------------
# Migrations
# ----------------------------------------------------------------------------
def test_migrations_create_the_tables(open_db):
    database = open_db()
    tables = set(inspect(database.engine).get_table_names())
    assert APP_TABLES | {"alembic_version"} <= tables


def test_models_match_the_migrations(open_db):
    """If this fails, models.py changed without a new migration (or the reverse)."""
    database = open_db()
    with database.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []


def test_solve_table_matches_solve_record():
    columns = {column.name for column in SolveRow.__table__.columns}
    # user_id (Phase 9) says whose solve it is; the record shown in the UI doesn't need it.
    assert columns == set(SolveRecord.__dataclass_fields__) | {"user_id"}


def test_upgrade_twice_is_harmless_and_downgrade_undoes_everything(open_db):
    database = open_db()
    upgrade(database)  # already at head: nothing to do
    downgrade(database, "base")
    assert not APP_TABLES & set(inspect(database.engine).get_table_names())
    upgrade(database)
    assert APP_TABLES <= set(inspect(database.engine).get_table_names())


def test_a_new_database_starts_without_tables(open_db):
    database = open_db(migrate=False)
    assert database.status()["schemaRevision"] is None


def test_upgrade_retries_while_the_server_wakes_up(monkeypatch):
    database = Database("sqlite://")
    calls, waits = [], []

    def flaky_upgrade(db, revision="head"):
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("SELECT 1", {}, Exception("server is waking up"))

    monkeypatch.setattr("backend.db.migrate.upgrade", flaky_upgrade)
    upgrade_with_retry(database, attempts=5, delay=2.0, sleep=waits.append)
    assert len(calls) == 3 and waits == [2.0, 2.0]


def test_upgrade_gives_up_with_a_clear_message(monkeypatch):
    def down(db, revision="head"):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr("backend.db.migrate.upgrade", down)
    with pytest.raises(StorageError, match="after 3 attempts: connection refused"):
        upgrade_with_retry(Database("sqlite://"), attempts=3, delay=0, sleep=lambda s: None)


def test_connect_uses_database_url_by_default(monkeypatch, tmp_path):
    import backend.config as config

    url = f"sqlite:///{(tmp_path / 'default.db').as_posix()}"
    monkeypatch.setattr(config, "RUNTIME", read_runtime_config({"DATABASE_URL": url}))
    database = connect()
    assert database.status()["location"].endswith("default.db")
    database.dispose()
