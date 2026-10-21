"""The JSON files used before Phase 3 are imported once, then kept as backups."""

import json

from backend.services.analytics import AnalyticsStore
from backend.services.legacy_import import import_legacy_json
from backend.services.profiles import ProfileStore
from backend.services.settings import SettingsStore


def write_old_files(folder):
    (folder / "settings.json").write_text(json.dumps({"camera_index": 2, "theme": "light"}))
    (folder / "hsv_profiles.json").write_text(json.dumps({"profiles": [
        {"name": "desk-lamp", "builtin": False, "ranges": {"R": {"h_min": 160, "h_max": 6}}},
        {"name": "default", "builtin": True, "ranges": {}},  # built-ins live in code: skipped
    ]}))
    (folder / "solve_history.json").write_text(json.dumps({"records": [
        {"id": "a1", "started_at": 1761000000.0, "finished_at": 1761000090.0, "move_count": 20,
         "quarter_turns": 23, "solve_ms": 3.1, "scan_seconds": 28.0, "execution_seconds": 90.0,
         "backend": "Kociemba Two-Phase (C)", "notation": "R U", "source": "scramble"},
        {"id": "old", "unknown_field": 1},  # written by an older version: skipped
    ]}))


def test_old_files_are_imported_once_and_kept_as_backups(open_db, tmp_path):
    write_old_files(tmp_path)
    database = open_db()
    messages = import_legacy_json(database, tmp_path)

    assert messages == [
        "Imported your settings from data/settings.json (kept as data/settings.json.imported)",
        "Imported 1 HSV profile(s) from data/hsv_profiles.json (kept as data/hsv_profiles.json.imported)",
        "Imported 1 solve(s) from data/solve_history.json (kept as data/solve_history.json.imported)",
    ]
    assert SettingsStore(database).current.camera_index == 2
    assert ProfileStore(database).get("desk-lamp").ranges["R"].h_min == 160
    assert AnalyticsStore(database).summary()["totalSolves"] == 1
    assert sorted(p.name for p in tmp_path.glob("*.json*")) == [
        "hsv_profiles.json.imported", "settings.json.imported", "solve_history.json.imported",
    ]
    assert import_legacy_json(database, tmp_path) == []  # nothing left to import


def test_existing_data_is_never_overwritten(open_db, tmp_path):
    database = open_db()
    SettingsStore(database).update({"camera_index": 1})
    (tmp_path / "settings.json").write_text(json.dumps({"camera_index": 3}))

    messages = import_legacy_json(database, tmp_path)
    assert messages == ["Skipped data/settings.json: the database already has this data"]
    assert SettingsStore(database).current.camera_index == 1
    assert (tmp_path / "settings.json").exists()  # left alone


def test_a_corrupt_file_is_skipped(open_db, tmp_path):
    (tmp_path / "solve_history.json").write_text("{ not json")
    messages = import_legacy_json(open_db(), tmp_path)
    assert len(messages) == 1 and messages[0].startswith("Skipped data/solve_history.json:")


def test_no_old_files_means_nothing_to_do(open_db, tmp_path):
    assert import_legacy_json(open_db(), tmp_path) == []
