"""Settings: the installation's (table ``app_settings``, one row), and per visitor (Phase 9).

Reads come from memory: the camera thread reads the settings for every frame and
must never wait for the network. Writes go to the database first, and the memory
copy changes only after the database has accepted them, so the two never disagree.
The vision engine is the only process that writes, so the memory copy is never stale.

Three stores with the same methods (``current``, ``get``, ``update``, ``reset``):

- ``SettingsStore``: the installation's settings. Locally (one person on a laptop) every
  session uses it, as before Phase 9.
- ``AccountSettings``: an account's own settings, saved in its ``users`` row.
- ``MemorySettings``: a guest's settings on the live site, kept for their visit only, so
  one visitor can't change the theme or palette for everyone.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from backend.config import Settings
from backend.db.database import Database
from backend.db.models import SettingsRow

log = logging.getLogger(__name__)


def merged(current: Settings, patch: Optional[Dict[str, Any]]) -> Settings:
    """``current`` with the known keys of ``patch`` changed (unknown keys are ignored)."""
    data = current.to_dict()
    for key, value in (patch or {}).items():
        if key in data:
            data[key] = value
    return Settings.from_dict(data)


class SettingsStore:
    """The installation's settings: read from memory, written through to the database."""

    #: The installation's row. Accounts keep their own settings in ``users`` (Phase 9).
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
            updated = merged(self._settings, patch)
            self._save(updated)  # database first ...
            self._settings = updated  # ... then memory
            return updated.to_dict()

    def reset(self) -> Dict[str, Any]:
        with self._write_lock:
            defaults = Settings()
            self._save(defaults)
            self._settings = defaults
            return defaults.to_dict()


class MemorySettings:
    """Settings that live only in memory: a guest's, on the live site (Phase 9)."""

    def __init__(self, seed: Settings) -> None:
        self._settings = Settings.from_dict(seed.to_dict())

    @property
    def current(self) -> Settings:
        return self._settings

    def get(self) -> Dict[str, Any]:
        return self._settings.to_dict()

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        self._settings = merged(self._settings, patch)
        return self._settings.to_dict()

    def reset(self) -> Dict[str, Any]:
        self._settings = Settings()
        return self._settings.to_dict()


class AccountSettings:
    """An account's own settings (Phase 9): saved in its ``users`` row, read from memory.

    A new account starts from ``seed`` (the installation's settings) until it changes one.
    """

    def __init__(self, accounts: Any, user_id: int, seed: Settings) -> None:
        self._accounts = accounts  # an AccountStore
        self._user_id = user_id
        self._write_lock = threading.Lock()
        data = accounts.load_settings(user_id)
        try:
            self._settings = Settings.from_dict(data) if data else Settings.from_dict(seed.to_dict())
        except (TypeError, AttributeError) as exc:
            log.warning("Ignoring unreadable settings of account %s: %s", user_id, exc)
            self._settings = Settings()

    @property
    def current(self) -> Settings:
        return self._settings

    def get(self) -> Dict[str, Any]:
        return self._settings.to_dict()

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Merge and save. Raises StorageError (then nothing changes)."""
        with self._write_lock:
            updated = merged(self._settings, patch)
            self._accounts.save_settings(self._user_id, updated.to_dict())  # database first ...
            self._settings = updated  # ... then memory
            return updated.to_dict()

    def reset(self) -> Dict[str, Any]:
        with self._write_lock:
            defaults = Settings()
            self._accounts.save_settings(self._user_id, defaults.to_dict())
            self._settings = defaults
            return defaults.to_dict()
