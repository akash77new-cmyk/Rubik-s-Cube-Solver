"""HSV colour profiles: built-in presets (in code) plus the user's own (in the database).

Moved here from ``backend/core/color.py`` in Phase 3: ``core`` stays pure (no file
or network I/O), and saving profiles is I/O. Like settings, profiles are read from
memory and written to the database first.
"""

from __future__ import annotations

import threading
from typing import Dict, List

from sqlalchemy import delete, select

from backend.core.color import BUILTIN_PRESETS, ColorProfile
from backend.core.cube import COLOR_CODES, COLOR_NAMES
from backend.db.database import Database
from backend.db.models import ColorProfileRow

#: Matches the ``name`` column (``String(64)``).
MAX_NAME_LENGTH = 64


def _copy(profile: ColorProfile) -> ColorProfile:
    return ColorProfile.from_dict(profile.to_dict())


class ProfileStore:
    """Built-in presets plus user-saved profiles."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._lock = threading.RLock()       # guards the memory copy
        self._write_lock = threading.Lock()  # one database write at a time
        self._profiles: Dict[str, ColorProfile] = {
            key: ColorProfile.preset(key) for key in BUILTIN_PRESETS
        }
        with self._db.transaction("load colour profiles") as session:
            rows = session.scalars(select(ColorProfileRow).order_by(ColorProfileRow.id)).all()
            saved = [ColorProfile.from_dict({"name": r.name, "ranges": r.ranges}) for r in rows]
        for profile in saved:
            if profile.name not in BUILTIN_PRESETS:
                self._profiles[profile.name] = profile

    # ------------------------------------------------------------------
    def names(self) -> List[str]:
        with self._lock:
            return list(self._profiles)

    def get(self, name: str) -> ColorProfile:
        with self._lock:
            return self._profiles.get(name) or ColorProfile.preset("default")

    def save(self, profile: ColorProfile) -> ColorProfile:
        """Create or replace a user profile. Raises ValueError or StorageError."""
        profile.builtin = profile.name in BUILTIN_PRESETS
        if profile.builtin:
            raise ValueError(f"'{profile.name}' is a built-in preset - save under a new name")
        if len(profile.name) > MAX_NAME_LENGTH:
            raise ValueError(f"Profile names can be at most {MAX_NAME_LENGTH} characters")
        ranges = {code: rng.to_dict() for code, rng in profile.ranges.items()}
        with self._write_lock:
            with self._db.transaction(f"save colour profile '{profile.name}'") as session:
                row = session.scalar(
                    select(ColorProfileRow).where(ColorProfileRow.name == profile.name)
                )
                if row is None:
                    session.add(ColorProfileRow(name=profile.name, ranges=ranges))
                else:
                    row.ranges = ranges
            with self._lock:
                # Keep a copy: the Calibration page goes on editing its draft, and
                # those edits must not change the saved profile until saved again.
                self._profiles[profile.name] = _copy(profile)
        return profile

    def delete(self, name: str) -> None:
        if name in BUILTIN_PRESETS:
            raise ValueError("Built-in presets cannot be deleted")
        with self._write_lock:
            with self._db.transaction(f"delete colour profile '{name}'") as session:
                session.execute(delete(ColorProfileRow).where(ColorProfileRow.name == name))
            with self._lock:
                self._profiles.pop(name, None)

    def to_dict(self) -> Dict[str, object]:
        with self._lock:
            return {
                "profiles": [p.to_dict() for p in self._profiles.values()],
                "builtins": list(BUILTIN_PRESETS),
                "colors": [{"code": code, "name": COLOR_NAMES[code]} for code in COLOR_CODES],
            }
