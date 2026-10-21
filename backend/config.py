"""Application paths, environment configuration and the user settings model.

Settings are stored in the database (``backend/services/settings.py``). A fresh
checkout works with sane defaults and never requires editing source to change a
camera index.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Union

from dotenv import load_dotenv

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Local development reads settings from a git-ignored .env file.
# Real environment variables (Render, Docker, CI) always win over it.
load_dotenv(PROJECT_ROOT / ".env", override=False)

ASSETS_DIR = PROJECT_ROOT / "assets"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DATA_DIR = Path(os.environ.get("CUBE_DATA_DIR") or PROJECT_ROOT / "data")
CACHE_DIR = PROJECT_ROOT / ".cache"
SOLVER_TABLE_DIR = CACHE_DIR / "twophase"
DOCS_DIR = PROJECT_ROOT / "docs"
#: Training data for the Phase 11 colour classifier (committed to git; see ml/data/README.md).
DATASET_DIR = Path(os.environ.get("CUBE_DATASET_DIR") or PROJECT_ROOT / "ml" / "data")

#: Local development database (used when DATABASE_URL is not set).
DEFAULT_SQLITE_FILE = DATA_DIR / "cube.db"

for _directory in (DATA_DIR, CACHE_DIR, SOLVER_TABLE_DIR):
    _directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------------------
# Runtime configuration (environment variables)
# --------------------------------------------------------------------------------------


class ConfigError(RuntimeError):
    """Raised at startup when the environment is misconfigured."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Everything this process reads from environment variables, in one place."""

    app_env: str                              # "development" | "production"
    web_host: str
    web_port: int
    engine_host: str
    engine_port: int
    secret_key: str = field(repr=False)       # hidden from repr(), so it never ends up in a log
    allowed_origins: Union[str, List[str]]    # "*" or a list of origins
    dataset_enabled: bool                     # may scans be saved as training data?
    database_url: str = field(repr=False)     # SQLAlchemy URL; may contain a password

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def normalize_database_url(raw: str) -> str:
    """Turn a pasted connection string into a SQLAlchemy URL.

    Neon gives ``postgresql://user:password@host/db?sslmode=require...``. SQLAlchemy
    needs to be told which driver to use (psycopg 3), so the scheme becomes
    ``postgresql+psycopg://``. SQLite URLs are used as they are.
    """
    url = raw.strip().strip("'\"")
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    if url.startswith(("postgresql+psycopg://", "sqlite://")):
        return url
    raise ConfigError(
        "DATABASE_URL must start with postgresql:// (Neon's connection string) or sqlite://"
    )


def read_runtime_config(env: Mapping[str, str]) -> RuntimeConfig:
    """Build the config from ``env`` (a plain mapping, so tests can pass a dict)."""
    app_env = (env.get("APP_ENV") or "development").strip().lower()
    if app_env not in ("development", "production"):
        raise ConfigError(f"APP_ENV must be 'development' or 'production', got {app_env!r}")
    production = app_env == "production"

    secret = env.get("FLASK_SECRET_KEY") or ""
    if not secret:
        if production:
            raise ConfigError("FLASK_SECRET_KEY must be set when APP_ENV=production")
        secret = "dev-only-insecure-key"

    raw_origins = (env.get("CUBE_ALLOWED_ORIGINS") or "*").strip()
    origins: Union[str, List[str]] = (
        "*" if raw_origins == "*"
        else [o.strip() for o in raw_origins.split(",") if o.strip()]
    )

    # Dataset collection needs a local camera and a permanent disk, so it is on by
    # default in development and off in production (Render's disk is temporary).
    raw_dataset = (env.get("CUBE_DATASET_ENABLED") or "").strip().lower()
    if raw_dataset == "":
        dataset_enabled = not production
    elif raw_dataset in ("1", "true", "yes", "on"):
        dataset_enabled = True
    elif raw_dataset in ("0", "false", "no", "off"):
        dataset_enabled = False
    else:
        raise ConfigError(f"CUBE_DATASET_ENABLED must be true or false, got {raw_dataset!r}")

    # Production must say where the data lives: Render's disk is wiped on every
    # deploy, so a silent local fallback would lose all history. Locally the data
    # lives in a SQLite file, so nothing needs setting up.
    raw_database_url = (env.get("DATABASE_URL") or "").strip()
    if not raw_database_url:
        if production:
            raise ConfigError(
                "DATABASE_URL must be set when APP_ENV=production (your Neon connection string)"
            )
        raw_database_url = f"sqlite:///{DEFAULT_SQLITE_FILE.as_posix()}"
    database_url = normalize_database_url(raw_database_url)

    return RuntimeConfig(
        app_env=app_env,
        web_host=env.get("CUBE_WEB_HOST") or ("0.0.0.0" if production else "127.0.0.1"),
        # Render injects PORT; an explicit CUBE_WEB_PORT still wins.
        web_port=int(env.get("CUBE_WEB_PORT") or env.get("PORT") or 8000),
        engine_host=env.get("CUBE_ENGINE_HOST") or "127.0.0.1",
        engine_port=int(env.get("CUBE_ENGINE_PORT") or 9999),
        secret_key=secret,
        allowed_origins=origins,
        dataset_enabled=dataset_enabled,
        database_url=database_url,
    )


RUNTIME = read_runtime_config(os.environ)

# Kept so existing imports keep working.
ENGINE_HOST = RUNTIME.engine_host
ENGINE_PORT = RUNTIME.engine_port
WEB_HOST = RUNTIME.web_host
WEB_PORT = RUNTIME.web_port


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
    #: Auto-capture waits until a side has been held still this long, so it is not
    #: grabbed while the cube is still being turned into place. 0 = capture at once.
    auto_capture_hold_ms: int = 1000

    # Overlays ---------------------------------------------------------------
    show_grid: bool = True
    show_labels: bool = True
    show_bounding_box: bool = True
    show_confidence: bool = True
    arrow_style: str = "neon"  # neon | solid | outline

    # Playback ---------------------------------------------------------------
    animation_speed: float = 1.0
    #: Auto play shows each move this long before the next one: enough time to read
    #: the instruction and do the turn by hand. Not affected by animation_speed.
    autoplay_interval_ms: int = 8000

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
