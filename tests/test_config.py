"""Runtime configuration read from environment variables.

Every test passes a plain dict to read_runtime_config(); os.environ is never changed.
"""

import os
from pathlib import Path

import pytest

from backend.config import (
    DATA_DIR,
    DATASET_DIR,
    DEFAULT_EMBED_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_SQLITE_FILE,
    ConfigError,
    normalize_database_url,
    read_runtime_config,
)

#: A connection string in the format Neon gives (made-up host and password).
NEON = (
    "postgresql://neondb_owner:s3cret@ep-cool-name-a1b2c3.ap-southeast-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)

#: The minimum a production config needs (DATABASE_URL since Phase 3).
PRODUCTION = {
    "APP_ENV": "production",
    "FLASK_SECRET_KEY": "x",
    "DATABASE_URL": "postgresql://user:pw@db.example/cube",
}


def test_data_dir_is_the_test_temp_folder():
    assert DATA_DIR == Path(os.environ["CUBE_DATA_DIR"])


def test_development_defaults():
    config = read_runtime_config({})
    assert config.app_env == "development"
    assert not config.is_production
    assert config.web_host == "127.0.0.1"
    assert config.web_port == 8000
    assert config.engine_host == "127.0.0.1"
    assert config.engine_port == 9999
    assert config.allowed_origins == "*"
    assert config.secret_key  # a dev-only key, never empty


def test_production_without_secret_raises():
    with pytest.raises(ConfigError, match="FLASK_SECRET_KEY"):
        read_runtime_config({"APP_ENV": "production"})


def test_production_binds_all_interfaces_on_render_port():
    config = read_runtime_config({**PRODUCTION, "FLASK_SECRET_KEY": "s3cret", "PORT": "10000"})
    assert config.is_production
    assert (config.web_host, config.web_port) == ("0.0.0.0", 10000)
    assert config.secret_key == "s3cret"


def test_cube_web_port_beats_port():
    config = read_runtime_config({"CUBE_WEB_PORT": "8123", "PORT": "10000"})
    assert config.web_port == 8123


def test_comma_separated_origins_become_a_list():
    config = read_runtime_config(
        {"CUBE_ALLOWED_ORIGINS": "https://a.example, https://b.example ,"}
    )
    assert config.allowed_origins == ["https://a.example", "https://b.example"]


def test_production_allows_only_its_own_origin_by_default():
    production = {**PRODUCTION, "FLASK_SECRET_KEY": "s3cret"}
    assert read_runtime_config(production).allowed_origins is None  # same origin only
    assert read_runtime_config({**production, "CUBE_ALLOWED_ORIGINS": "*"}).allowed_origins == "*"


def test_invalid_app_env_raises():
    with pytest.raises(ConfigError, match="APP_ENV"):
        read_runtime_config({"APP_ENV": "staging"})


def test_dataset_collection_defaults_follow_app_env():
    assert read_runtime_config({}).dataset_enabled is True
    assert read_runtime_config(PRODUCTION).dataset_enabled is False


def test_dataset_collection_can_be_set_explicitly():
    assert read_runtime_config({"CUBE_DATASET_ENABLED": "0"}).dataset_enabled is False
    production = {**PRODUCTION, "CUBE_DATASET_ENABLED": "yes"}
    assert read_runtime_config(production).dataset_enabled is True
    with pytest.raises(ConfigError):
        read_runtime_config({"CUBE_DATASET_ENABLED": "maybe"})


def test_dataset_dir_is_isolated_in_tests():
    assert "cube-test-dataset-" in str(DATASET_DIR)


# --- DATABASE_URL (Phase 3) --------------------------------------------------
def test_neon_connection_string_gets_the_psycopg_driver():
    url = normalize_database_url(NEON)
    assert url.startswith("postgresql+psycopg://neondb_owner:s3cret@ep-cool-name")
    assert url.endswith("?sslmode=require&channel_binding=require")
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"


def test_pasted_quotes_and_spaces_are_removed():
    assert normalize_database_url(f"  '{NEON}'\n") == normalize_database_url(NEON)


def test_sqlite_urls_are_kept_and_other_schemes_rejected():
    assert normalize_database_url("sqlite:///data/cube.db") == "sqlite:///data/cube.db"
    with pytest.raises(ConfigError, match="postgresql://"):
        normalize_database_url("mysql://u:p@h/db")
    with pytest.raises(ConfigError):
        normalize_database_url("psql 'postgresql://u:p@h/db'")


def test_development_defaults_to_a_sqlite_file_in_the_data_folder():
    config = read_runtime_config({})
    assert config.database_url == f"sqlite:///{DEFAULT_SQLITE_FILE.as_posix()}"


def test_production_requires_database_url():
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        read_runtime_config({"APP_ENV": "production", "FLASK_SECRET_KEY": "x"})


def test_secrets_never_appear_in_the_config_repr():
    config = read_runtime_config({"DATABASE_URL": NEON, "FLASK_SECRET_KEY": "top-secret"})
    assert "s3cret" not in repr(config) and "top-secret" not in repr(config)


# --- AI settings (Phase 4) --------------------------------------------------------
def test_ai_is_optional_with_safe_defaults():
    config = read_runtime_config(PRODUCTION)  # production works without a Gemini key
    assert config.gemini_api_key == ""
    assert config.gemini_model == DEFAULT_GEMINI_MODEL
    assert (config.gemini_base_url, config.gemini_thinking_level) == ("", "")
    assert (config.ai_requests_per_minute, config.ai_requests_per_day) == (10, 200)
    assert config.gemini_embed_model == DEFAULT_EMBED_MODEL == "gemini-embedding-001"


def test_ai_settings_from_the_environment():
    config = read_runtime_config(
        {
            "GEMINI_API_KEY": " key-123 ",
            "GEMINI_MODEL": "gemini-3.8-flash",
            "GEMINI_THINKING_LEVEL": "LOW",
            "AI_REQUESTS_PER_MINUTE": "5",
            "AI_REQUESTS_PER_DAY": "0",
        }
    )
    assert (config.gemini_api_key, config.gemini_model, config.gemini_thinking_level) == (
        "key-123", "gemini-3.8-flash", "low",
    )
    assert (config.ai_requests_per_minute, config.ai_requests_per_day) == (5, 0)
    assert "key-123" not in repr(config)


def test_bad_ai_settings_are_refused():
    with pytest.raises(ConfigError, match="GEMINI_THINKING_LEVEL"):
        read_runtime_config({"GEMINI_THINKING_LEVEL": "extreme"})
    with pytest.raises(ConfigError, match="AI_REQUESTS_PER_DAY must be a whole number"):
        read_runtime_config({"AI_REQUESTS_PER_DAY": "lots"})
    with pytest.raises(ConfigError, match="AI_REQUESTS_PER_MINUTE must be 0 or more"):
        read_runtime_config({"AI_REQUESTS_PER_MINUTE": "-1"})
