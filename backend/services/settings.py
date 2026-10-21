"""User settings, stored in the database (table ``app_settings``, one row).

Reads come from memory: the camera thread reads the settings for every frame and
must never wait for the network. Writes go to the database first, and the memory
copy changes only after the database has accepted them, so the two never disagree.
The vision engine is the only process that writes, so the memory copy is never stale.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict

from backend.config import Settings
from backend.db.database import Database
from backend.db.models import SettingsRow

log = logging.getLogger(__name__)


class SettingsStore:
    """The current settings: read from memory, written through to the database."""

    #: One settings row until accounts (Phase 9) give every user their own.
    ROW_ID = 1

    def __init__(self, database: Database) -> None:
        self._db = database
        self._write_lock = threading.Lock()  # one write at a time
        self._settings = self._load()

    # ------------------------------------------------------------------
    def _load(self) -> Settings:
        with self._db.transaction("load settings") as session:
            row = session.get(SettingsRow, self.ROW_ID)
            data = row.data if row is not None else None
        if data is None:
            return Settings()
        try:
            return Settings.from_dict(data)
        except (TypeError, AttributeError) as exc:  # unreadable (edited by hand?): use defaults
            log.warning("Ignoring unreadable saved settings: %s", exc)
            return Settings()

    def _save(self, settings: Settings) -> None:
        with self._db.transaction("save settings") as session:
            row = session.get(SettingsRow, self.ROW_ID)
            if row is None:
                session.add(SettingsRow(id=self.ROW_ID, data=settings.to_dict()))
            else:
                row.data = settings.to_dict()

    # ------------------------------------------------------------------
    @property
    def current(self) -> Settings:
        # No lock: reading one attribute is atomic, and a write swaps in a new object.
        return self._settings

    def get(self) -> Dict[str, Any]:
        return self._settings.to_dict()

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``patch`` into the current settings and save. Raises StorageError."""
        with self._write_lock:
            merged = self._settings.to_dict()
            for key, value in (patch or {}).items():
                if key in merged:
                    merged[key] = value
            updated = Settings.from_dict(merged)
            self._save(updated)  # database first ...
            self._settings = updated  # ... then memory
            return updated.to_dict()

    def reset(self) -> Dict[str, Any]:
        with self._write_lock:
            defaults = Settings()
            self._save(defaults)
            self._settings = defaults
            return defaults.to_dict()
