"""Application paths and persisted user settings.

Settings live in ``<project>/data/settings.json`` so that a fresh checkout works
with sane defaults and never requires editing source to change a camera index.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = PROJECT_ROOT / ".cache"
SOLVER_TABLE_DIR = CACHE_DIR / "twophase"
DOCS_DIR = PROJECT_ROOT / "docs"

SETTINGS_FILE = DATA_DIR / "settings.json"
PROFILES_FILE = DATA_DIR / "hsv_profiles.json"
HISTORY_FILE = DATA_DIR / "solve_history.json"

for _directory in (DATA_DIR, CACHE_DIR, SOLVER_TABLE_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------------------

#: TCP port used by the vision engine process. The web server connects to it as a client.
ENGINE_HOST = os.environ.get("CUBE_ENGINE_HOST", "127.0.0.1")
ENGINE_PORT = int(os.environ.get("CUBE_ENGINE_PORT", "9999"))

#: HTTP port for the Flask + Socket.IO server that serves the UI.
WEB_HOST = os.environ.get("CUBE_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.environ.get("CUBE_WEB_PORT", "8000"))


# --------------------------------------------------------------------------------------
# Settings model
# --------------------------------------------------------------------------------------


@dataclass
class Settings:
    """User-tunable options surfaced on the Settings page."""

    # Camera -----------------------------------------------------------------
    camera_index: int = 0
    frame_width: int = 960
    frame_height: int = 720
    target_fps: int = 30
    mirror_camera: bool = True

    # Detection --------------------------------------------------------------
    sample_radius: int = 10
    grid_spacing: int = 96
    grid_offset_y: int = 0
    min_confidence: float = 0.35
    active_profile: str = "default"

    # Overlays ---------------------------------------------------------------
    show_grid: bool = True
    show_labels: bool = True
    show_bounding_box: bool = True
    show_confidence: bool = True
    arrow_style: str = "neon"  # neon | solid | outline

    # Playback ---------------------------------------------------------------
    animation_speed: float = 1.0
    autoplay_interval_ms: int = 900

    # Appearance -------------------------------------------------------------
    theme: str = "dark"  # dark | midnight | light
    accent: str = "violet"
    cube_palette: Dict[str, str] = field(
        default_factory=lambda: {
            "W": "#F8FAFC",
            "Y": "#FACC15",
            "R": "#EF4444",
            "O": "#F97316",
            "G": "#22C55E",
            "B": "#3B82F6",
        }
    )

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in (payload or {}).items() if k in known}
        return cls(**clean)


class SettingsStore:
    """Thread-safe JSON-backed settings store."""

    def __init__(self, path: Path = SETTINGS_FILE) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._settings = self._read()

    # ------------------------------------------------------------------
    def _read(self) -> Settings:
        if self._path.exists():
            try:
                return Settings.from_dict(json.loads(self._path.read_text("utf-8")))
            except (json.JSONDecodeError, OSError, TypeError):
                pass  # corrupt file -> fall back to defaults rather than crashing
        return Settings()

    def _write(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._settings.to_dict(), indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    @property
    def current(self) -> Settings:
        with self._lock:
            return self._settings

    def get(self) -> Dict[str, Any]:
        with self._lock:
            return self._settings.to_dict()

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """Merge ``patch`` into the current settings and persist."""
        with self._lock:
            merged = self._settings.to_dict()
            for key, value in (patch or {}).items():
                if key in merged:
                    merged[key] = value
            self._settings = Settings.from_dict(merged)
            self._write()
            return self._settings.to_dict()

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            self._settings = Settings()
            self._write()
            return self._settings.to_dict()


settings_store = SettingsStore()
