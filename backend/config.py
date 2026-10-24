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
#: The trained colour classifier, written by ml/train.py (Phase 11).
MODEL_DIR = Path(os.environ.get("CUBE_MODEL_DIR") or PROJECT_ROOT / "ml" / "models")

#: Local development database (used when DATABASE_URL is not set).
DEFAULT_SQLITE_FILE = DATA_DIR / "cube.db"

#: Gemini model for the AI features (Phase 4): Google's suggestion for new projects
#: in Oct 2026 - fast, cheap, and on the free tier. Change it with GEMINI_MODEL.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
#: Embedding model for the RAG coach (Phase 7). Change it with GEMINI_EMBED_MODEL.
DEFAULT_EMBED_MODEL = "gemini-embedding-001"
THINKING_LEVELS = ("minimal", "low", "medium", "high")

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
    allowed_origins: Union[None, str, List[str]]  # None = same origin only, "*", or a list
    dataset_enabled: bool                     # may scans be saved as training data?
    database_url: str = field(repr=False)     # SQLAlchemy URL; may contain a password
    # AI (Phase 4). Without a key, every AI feature gives its built-in answer.
    gemini_api_key: str = field(repr=False)   # a secret, like the database URL
    gemini_model: str
    gemini_base_url: str                      # "" = Google's; tests may point it elsewhere
    gemini_thinking_level: str                # "" = the model's default
    gemini_embed_model: str                   # the RAG coach's embedding model (Phase 7)
    ai_requests_per_minute: int               # the app's own limits, below Google's
    ai_requests_per_day: int
    # Phase 11: "auto" (the CNN if it beat HSV on its test scans), "hsv" or "cnn".
    color_model: str = "auto"

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


def _count(env: Mapping[str, str], name: str, default: int) -> int:
    """A whole number >= 0 from the environment, or ``default`` if not set."""
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}") from None
    if value < 0:
        raise ConfigError(f"{name} must be 0 or more, got {value}")
    return value


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

    # Which web pages may open a Socket.IO connection. In production, by default only
    # the app's own page (same origin): another site can't drive the live demo from a
    # visitor's browser. Locally any origin, so the Vite dev server keeps working.
    raw_origins = (env.get("CUBE_ALLOWED_ORIGINS") or "").strip()
    origins: Union[None, str, List[str]]
    if not raw_origins:
        origins = None if production else "*"
    elif raw_origins == "*":
        origins = "*"
    else:
        origins = [o.strip() for o in raw_origins.split(",") if o.strip()]

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

    color_model = (env.get("CUBE_COLOR_MODEL") or "").strip().lower() or "auto"
    if color_model not in ("auto", "hsv", "cnn"):
        raise ConfigError(f"CUBE_COLOR_MODEL must be auto, hsv or cnn, got {color_model!r}")

    thinking_level = (env.get("GEMINI_THINKING_LEVEL") or "").strip().lower()
    if thinking_level and thinking_level not in THINKING_LEVELS:
        raise ConfigError(f"GEMINI_THINKING_LEVEL must be one of {', '.join(THINKING_LEVELS)} (or empty)")

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
        gemini_api_key=(env.get("GEMINI_API_KEY") or "").strip(),
        gemini_model=(env.get("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL,
        gemini_base_url=(env.get("GEMINI_BASE_URL") or "").strip(),
        gemini_thinking_level=thinking_level,
        gemini_embed_model=(env.get("GEMINI_EMBED_MODEL") or "").strip() or DEFAULT_EMBED_MODEL,
        ai_requests_per_minute=_count(env, "AI_REQUESTS_PER_MINUTE", 10),
        ai_requests_per_day=_count(env, "AI_REQUESTS_PER_DAY", 200),
        color_model=color_model,
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
