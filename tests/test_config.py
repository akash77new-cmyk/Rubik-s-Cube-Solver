"""Runtime configuration read from environment variables.

Every test passes a plain dict to read_runtime_config(); os.environ is never changed.
"""

import os
from pathlib import Path

import pytest

from backend.config import DATA_DIR, DATASET_DIR, ConfigError, read_runtime_config


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
    config = read_runtime_config(
        {"APP_ENV": "production", "FLASK_SECRET_KEY": "s3cret", "PORT": "10000"}
    )
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


def test_invalid_app_env_raises():
    with pytest.raises(ConfigError, match="APP_ENV"):
        read_runtime_config({"APP_ENV": "staging"})


def test_dataset_collection_defaults_follow_app_env():
    assert read_runtime_config({}).dataset_enabled is True
    production = {"APP_ENV": "production", "FLASK_SECRET_KEY": "x"}
    assert read_runtime_config(production).dataset_enabled is False


def test_dataset_collection_can_be_set_explicitly():
    assert read_runtime_config({"CUBE_DATASET_ENABLED": "0"}).dataset_enabled is False
    production = {"APP_ENV": "production", "FLASK_SECRET_KEY": "x", "CUBE_DATASET_ENABLED": "yes"}
    assert read_runtime_config(production).dataset_enabled is True
    with pytest.raises(ConfigError):
        read_runtime_config({"CUBE_DATASET_ENABLED": "maybe"})


def test_dataset_dir_is_isolated_in_tests():
    assert "cube-test-dataset-" in str(DATASET_DIR)
