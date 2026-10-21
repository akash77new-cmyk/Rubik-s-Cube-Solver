"""Database-backed stores for tests: a fresh in-memory SQLite database each time,
built by the real migrations, so tests never touch data/ or a real server."""

from typing import Any, Dict

from backend.db import connect
from backend.services.analytics import AnalyticsStore
from backend.services.profiles import ProfileStore
from backend.services.settings import SettingsStore


def memory_stores() -> Dict[str, Any]:
    """Keyword arguments for SolveSession: settings, profiles, analytics, database."""
    database = connect("sqlite://")
    return {
        "settings": SettingsStore(database),
        "profiles": ProfileStore(database),
        "analytics": AnalyticsStore(database),
        "database": database,
    }
