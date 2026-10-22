"""The session reports the database and says clearly when something was not saved."""

import pytest

from backend.core.cube import CubeState
from backend.core.moves import invert_sequence, parse_sequence
from backend.core.solver import Solution, SolverEngine
from backend.db import StorageError
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from tests.storage import memory_stores


@pytest.fixture
def session():
    events = []
    stores = memory_stores()
    s = SolveSession(
        **stores,
        solver=SolverEngine(),
        logs=LogBus(),
        publish_event=lambda event, data: events.append((event, data)),
        publish_frame=lambda jpeg: None,
    )
    s.events = events
    s.db = stores["database"]
    return s


def break_database(session, monkeypatch):
    def broken(what):
        raise StorageError(f"Could not {what}: connection refused")

    monkeypatch.setattr(session.db, "transaction", broken)


def test_snapshot_reports_the_database(session):
    database = session.snapshot()["database"]
    assert database["backend"] == "SQLite"
    assert database["connected"] is True
    assert database["schemaRevision"] == "0002"


def test_check_connection_command(session):
    result = session.handle_command("database.check", {})
    assert result["ok"] is True and result["database"]["connected"] is True


def test_check_connection_tells_the_browser(session):
    """The ack only says "queued", so the result must arrive as an event (toast)."""
    session.handle_command("database.check", {})
    (status,) = [data for event, data in session.events if event == "database:checked"]
    assert status["connected"] is True and status["backend"] == "SQLite"


def test_a_failed_check_tells_the_browser_why(session, monkeypatch):
    down = dict(session.db.status(), connected=False, error="connection refused")
    monkeypatch.setattr(session.db, "check", lambda: down)
    result = session.handle_command("database.check", {})
    assert result["ok"] is False
    assert ("database:checked", down) in session.events


def test_a_failed_settings_save_is_reported_and_changes_nothing(session, monkeypatch):
    break_database(session, monkeypatch)
    result = session.handle_command("settings.update", {"target_fps": 12})
    assert result == {"ok": False, "error": "Could not save settings: connection refused"}
    assert session.snapshot()["settings"]["target_fps"] == 30
    assert ("storage:error", {"message": "Could not save settings: connection refused"}) in session.events


def test_the_cube_is_still_solved_when_history_cannot_be_saved(session, monkeypatch):
    scramble = parse_sequence("R U")
    cube = CubeState.solved().apply_sequence(scramble)
    moves = invert_sequence(scramble)
    states = [cube]
    for move in moves:
        states.append(states[-1].apply(move))
    session._cube = cube
    session._solution = Solution(moves, "test", 0.0, cube.to_facelet_string(), cube, states)
    session._solve_id = "unsaved"
    session._mode = "solution"
    break_database(session, monkeypatch)

    for _ in range(len(moves) + 1):  # the hold step, then every move
        session.handle_command("playback.next", {})

    snapshot = session.snapshot()
    assert snapshot["playback"]["completed"] and snapshot["mode"] == "complete"
    assert snapshot["analytics"]["totalSolves"] == 0
    assert any(event == "storage:error" for event, _ in session.events)
