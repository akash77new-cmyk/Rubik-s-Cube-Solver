"""One-time import of the JSON files the app used before Phase 3.

Until Phase 3, data lived in three files in ``data/``. On the first start with a
database, each file that exists is copied into its table, but only while that table
is still empty, so nothing is ever imported twice or overwritten. An imported file
is then renamed to ``<name>.imported``: it stays on disk as a backup, and is never
read again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.core.color import BUILTIN_PRESETS, ColorProfile
from backend.db.database import Database, StorageError
from backend.db.models import ColorProfileRow, SettingsRow, SolveRow
from backend.services.analytics import SolveRecord, row_from_record
from backend.services.profiles import MAX_NAME_LENGTH
from backend.services.settings import SettingsStore

SETTINGS_FILE = "settings.json"
PROFILES_FILE = "hsv_profiles.json"
HISTORY_FILE = "solve_history.json"
IMPORTED_SUFFIX = ".imported"


def _count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _import_settings(session: Session, payload: Dict[str, Any]) -> Optional[str]:
    if session.get(SettingsRow, SettingsStore.ROW_ID) is not None:
        return None
    session.add(SettingsRow(id=SettingsStore.ROW_ID, data=Settings.from_dict(payload).to_dict()))
    return "your settings"


def _import_profiles(session: Session, payload: Dict[str, Any]) -> Optional[str]:
    if _count(session, ColorProfileRow):
        return None
    names = set()
    for item in payload.get("profiles", []):
        profile = ColorProfile.from_dict(item)
        if profile.name in BUILTIN_PRESETS or profile.name in names:
            continue
        if len(profile.name) > MAX_NAME_LENGTH:
            continue
        names.add(profile.name)
        ranges = {code: rng.to_dict() for code, rng in profile.ranges.items()}
        session.add(ColorProfileRow(name=profile.name, ranges=ranges))
    return f"{len(names)} HSV profile(s)"


def _import_history(session: Session, payload: Dict[str, Any]) -> Optional[str]:
    if _count(session, SolveRow):
        return None
    ids = set()
    for item in payload.get("records", []):
        try:
            record = SolveRecord(**item)
        except TypeError:
            continue  # written by an older version: same rule as the old JSON loader
        if record.id in ids:
            continue
        ids.add(record.id)
        session.add(row_from_record(record))
    return f"{len(ids)} solve(s)"


IMPORTERS: Dict[str, Callable[[Session, Dict[str, Any]], Optional[str]]] = {
    SETTINGS_FILE: _import_settings,
    PROFILES_FILE: _import_profiles,
    HISTORY_FILE: _import_history,
}


def import_legacy_json(database: Database, data_dir: Path) -> List[str]:
    """Import the old JSON files that exist. Returns one message per file found."""
    messages: List[str] = []
    for name, importer in IMPORTERS.items():
        path = Path(data_dir) / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("not a JSON object")
            with database.transaction(f"import {name}") as session:
                imported = importer(session, payload)
        except (OSError, ValueError, TypeError, AttributeError, StorageError) as exc:
            messages.append(f"Skipped data/{name}: {exc}")
            continue
        if imported is None:
            messages.append(f"Skipped data/{name}: the database already has this data")
            continue
        try:
            path.replace(path.with_name(name + IMPORTED_SUFFIX))
        except OSError as exc:  # harmless: the table is no longer empty, so no second import
            messages.append(f"Imported {imported} from data/{name} (could not rename it: {exc})")
            continue
        messages.append(f"Imported {imported} from data/{name} (kept as data/{name}{IMPORTED_SUFFIX})")
    return messages
