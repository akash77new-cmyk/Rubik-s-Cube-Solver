"""Settings, HSV profiles and solve history are kept in the database.

Each test "restarts the app" by opening the database a second time and checks that
the data is still there. Runs on SQLite, and on PostgreSQL too when
CUBE_TEST_POSTGRES_URL is set (see conftest.py).
"""

import time

import pytest

from backend.config import Settings
from backend.core.color import ColorProfile
from backend.db import StorageError
from backend.services.analytics import AnalyticsStore, SolveRecord, record_from_row, row_from_record
from backend.services.profiles import MAX_NAME_LENGTH, ProfileStore
from backend.services.settings import SettingsStore


def solve(solve_id: str, finished_at: float, moves: int = 20) -> SolveRecord:
    return SolveRecord(
        id=solve_id, started_at=finished_at - 90.5, finished_at=finished_at,
        move_count=moves, quarter_turns=moves + 3, solve_ms=4.25, scan_seconds=31.0,
        execution_seconds=90.5, backend="Kociemba Two-Phase (C)", notation="R U R' U'",
        face_distribution={"R": 2, "U": 2}, turn_distribution={"cw": 2, "ccw": 2, "double": 0},
        detection_confidence=0.84, source="scan",
    )


def failing(database, monkeypatch):
    """Make every database transaction fail, as if the server had gone away."""

    def broken(what):
        raise StorageError(f"Could not {what}: connection refused")

    monkeypatch.setattr(database, "transaction", broken)


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
def test_a_new_database_starts_with_default_settings(open_db):
    assert SettingsStore(open_db()).current == Settings()


def test_settings_survive_a_restart(open_db):
    store = SettingsStore(open_db())
    store.update({"camera_index": 1, "autoplay_interval_ms": 5000, "not_a_setting": 7})
    restarted = SettingsStore(open_db()).current
    assert (restarted.camera_index, restarted.autoplay_interval_ms) == (1, 5000)
    assert not hasattr(restarted, "not_a_setting")


def test_reset_is_saved_too(open_db):
    store = SettingsStore(open_db())
    store.update({"theme": "light"})
    store.reset()
    assert SettingsStore(open_db()).current.theme == "dark"


def test_nested_settings_are_saved(open_db):
    store = SettingsStore(open_db())
    palette = dict(store.current.cube_palette, R="#FF0000")
    store.update({"cube_palette": palette})
    assert SettingsStore(open_db()).current.cube_palette["R"] == "#FF0000"


def test_a_failed_save_changes_nothing(open_db, monkeypatch):
    database = open_db()
    store = SettingsStore(database)
    failing(database, monkeypatch)
    with pytest.raises(StorageError, match="Could not save settings"):
        store.update({"target_fps": 12})
    assert store.current.target_fps == 30  # memory still matches the database


# ----------------------------------------------------------------------------
# HSV profiles
# ----------------------------------------------------------------------------
def test_profiles_survive_a_restart(open_db):
    store = ProfileStore(open_db())
    profile = ColorProfile.preset("default")
    profile.name = "desk-lamp"
    profile.ranges["R"].h_min = 165
    store.save(profile)
    restarted = ProfileStore(open_db())
    assert restarted.names() == ["default", "low-light", "legacy", "desk-lamp"]
    assert restarted.get("desk-lamp").ranges["R"].h_min == 165
    assert restarted.get("desk-lamp").builtin is False


def test_saving_again_replaces_the_profile(open_db):
    store = ProfileStore(open_db())
    store.save(ColorProfile(name="lamp"))
    updated = ColorProfile(name="lamp")
    updated.ranges["G"].s_min = 99
    store.save(updated)
    restarted = ProfileStore(open_db())
    assert restarted.names().count("lamp") == 1
    assert restarted.get("lamp").ranges["G"].s_min == 99


def test_deleted_profiles_stay_deleted(open_db):
    store = ProfileStore(open_db())
    store.save(ColorProfile(name="temp"))
    store.delete("temp")
    assert "temp" not in ProfileStore(open_db()).names()


def test_built_in_presets_are_protected(open_db):
    store = ProfileStore(open_db())
    with pytest.raises(ValueError, match="built-in"):
        store.save(ColorProfile(name="default"))
    with pytest.raises(ValueError, match="cannot be deleted"):
        store.delete("legacy")


def test_profile_names_fit_the_column(open_db):
    store = ProfileStore(open_db())
    store.save(ColorProfile(name="x" * MAX_NAME_LENGTH))
    with pytest.raises(ValueError, match="at most 64"):
        store.save(ColorProfile(name="x" * (MAX_NAME_LENGTH + 1)))


def test_editing_a_draft_after_saving_does_not_change_the_saved_profile(open_db):
    store = ProfileStore(open_db())
    draft = ColorProfile(name="lamp")
    store.save(draft)
    draft.ranges["B"].h_min = 1  # the Calibration page keeps editing its draft
    assert store.get("lamp").ranges["B"].h_min != 1


# ----------------------------------------------------------------------------
# Solve history
# ----------------------------------------------------------------------------
def test_solve_history_survives_a_restart_in_order(open_db):
    store = AnalyticsStore(open_db())
    now = time.time()
    store.record(solve("late", now, moves=19))
    store.record(solve("early", now - 3600, moves=22))
    summary = AnalyticsStore(open_db()).summary()
    assert summary["totalSolves"] == 2
    assert [r["id"] for r in summary["recent"]] == ["late", "early"]  # newest first
    assert summary["bestMoveCount"] == 19
    assert summary["faceDistribution"]["R"] == 4


def test_a_solve_round_trips_exactly(open_db):
    store = AnalyticsStore(open_db())
    original = solve("exact", 1_761_050_000.123456)
    store.record(original)
    (restored,) = AnalyticsStore(open_db())._records
    restored_values, original_values = restored.to_dict(), original.to_dict()
    for name in ("started_at", "finished_at"):  # timestamps keep microseconds
        assert abs(restored_values.pop(name) - original_values.pop(name)) < 1e-5
    assert restored_values == original_values


def test_rows_convert_both_ways():
    record = solve("conv", 1_761_050_000.5)
    row = row_from_record(record)
    assert row.finished_at.tzinfo is not None
    assert record_from_row(row) == record


def test_history_is_no_longer_capped_at_200(open_db):
    store = AnalyticsStore(open_db())
    now = time.time()
    for index in range(205):
        store.record(solve(f"s{index}", now + index))
    assert AnalyticsStore(open_db()).summary()["totalSolves"] == 205


def test_clearing_history_is_saved(open_db):
    store = AnalyticsStore(open_db())
    store.record(solve("gone", time.time()))
    store.clear()
    assert AnalyticsStore(open_db()).summary()["totalSolves"] == 0


def test_a_failed_save_is_not_counted(open_db, monkeypatch):
    database = open_db()
    store = AnalyticsStore(database)
    failing(database, monkeypatch)
    with pytest.raises(StorageError, match="Could not save the solve"):
        store.record(solve("lost", time.time()))
    assert store.summary()["totalSolves"] == 0
