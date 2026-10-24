"""Shared test setup.

backend.config reads environment variables at import time, so they are set here,
before any test module imports the backend. Tests must never touch the real data/
folder, the committed ml/data/ dataset, the trained model in ml/models/ or a real
database, so CUBE_DATA_DIR, CUBE_DATASET_DIR and CUBE_MODEL_DIR point at throwaway temp
folders, and DATABASE_URL is emptied (an empty value wins over .env, so the default -
SQLite in the temp folder - is used).

Database tests run on SQLite, and also on PostgreSQL when CUBE_TEST_POSTGRES_URL
points at a throwaway Postgres server (see docs: the Docker command in README.md).
"""

import os
import tempfile

os.environ["APP_ENV"] = "development"
os.environ["CUBE_DATA_DIR"] = tempfile.mkdtemp(prefix="cube-test-data-")
os.environ["CUBE_DATASET_DIR"] = tempfile.mkdtemp(prefix="cube-test-dataset-")
os.environ["CUBE_MODEL_DIR"] = tempfile.mkdtemp(prefix="cube-test-model-")
os.environ["DATABASE_URL"] = ""

import pytest  # noqa: E402 - the environment above must be set first
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from backend.config import normalize_database_url  # noqa: E402
from backend.db import connect  # noqa: E402
from backend.db.models import Base  # noqa: E402

POSTGRES_URL = os.environ.get("CUBE_TEST_POSTGRES_URL", "")
#: Every database test runs once per backend listed here.
BACKENDS = ["sqlite", "postgres"] if POSTGRES_URL else ["sqlite"]


def _empty_postgres(url: str) -> None:
    """Drop this app's tables (and nothing else) so each test starts empty."""
    engine = create_engine(url, poolclass=NullPool)
    with engine.begin() as connection:
        Base.metadata.drop_all(connection)
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()


@pytest.fixture(params=BACKENDS)
def db_url(request, tmp_path):
    """URL of an empty database: a SQLite file, and Postgres when CUBE_TEST_POSTGRES_URL is set."""
    if request.param == "sqlite":
        return f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    url = normalize_database_url(POSTGRES_URL)
    if "neon.tech" in url:
        pytest.fail("CUBE_TEST_POSTGRES_URL points at Neon: tests delete tables, use a throwaway server")
    _empty_postgres(url)
    return url


@pytest.fixture
def open_db(db_url):
    """``open_db()`` opens the test database the way the engine does (migrations
    included). Call it again to "restart the app". Every one is closed afterwards."""
    opened = []

    def _open(migrate: bool = True):
        database = connect(db_url, migrate=migrate)
        opened.append(database)
        return database

    yield _open
    for database in opened:
        database.dispose()
