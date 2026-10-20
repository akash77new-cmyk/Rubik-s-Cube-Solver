"""Auto-capture waits until a side has been held still for the hold time.

A fake clock replaces real time, so "held for 1 second" takes milliseconds to test and
never depends on how fast the test machine is. The hold is measured in seconds, not
frames, so a low frame rate (10 fps) keeps the tests quick without changing the logic.
The detector needs 6 identical frames (0.6 s here) before a read counts as stable.
"""

import pytest

from backend.config import SettingsStore
from backend.core.color import ProfileStore
from backend.core.cube import CubeState, random_scramble
from backend.core.solver import SolverEngine
from backend.services.analytics import AnalyticsStore
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from tests.synthetic import synthetic_face

FPS = 10


@pytest.fixture
def cube():
    return CubeState.solved().apply_sequence(random_scramble(20, seed=21))


def new_session(tmp_path):
    events = []
    s = SolveSession(
        settings=SettingsStore(tmp_path / "settings.json"),
        profiles=ProfileStore(tmp_path / "profiles.json"),
        solver=SolverEngine(),
        logs=LogBus(),
        analytics=AnalyticsStore(tmp_path / "history.json"),
        publish_event=lambda event, data: events.append((event, data)),
        publish_frame=lambda jpeg: None,
    )
    s.events = events
    return s


@pytest.fixture
def session(tmp_path):
    s = new_session(tmp_path)
    s.now = 100.0
    s._clock = lambda: s.now  # fake clock, moved forward by show()
    s.update_settings({"auto_capture_hold_ms": 1000})
    s.handle_command("scan.auto", {"enabled": True})  # manual capture is the default
    s.start_scan(open_camera=False)
    return s


def test_manual_capture_is_the_default(tmp_path):
    assert new_session(tmp_path).snapshot()["scan"]["autoCapture"] is False


def show(session, colors, seconds):
    """Hold one side still in front of the camera for ``seconds``."""
    frame = synthetic_face(colors)
    for _ in range(round(seconds * FPS)):
        session._process_frame(frame.copy())
        session.now += 1 / FPS


def test_a_side_is_captured_only_after_the_hold_time(session, cube):
    show(session, cube.face("F"), 1.0)  # stable after 0.6 s, then held for 0.4 s
    assert "F" not in session._scanned
    assert 0.3 < session._hold_progress < 0.5 and session._hold_face == "F"
    show(session, cube.face("F"), 1.0)  # now held for more than 1 s
    assert list(session._scanned) == ["F"]
    assert session._scanned["F"]["auto"]


def test_moving_the_cube_starts_the_wait_again(session, cube):
    show(session, cube.face("F"), 1.0)
    show(session, cube.face("R"), 0.5)  # turned to another side before the hold ended
    show(session, cube.face("F"), 1.0)  # back again: the wait starts from zero
    assert session._scanned == {}
    show(session, cube.face("F"), 1.0)
    assert list(session._scanned) == ["F"]


def test_the_hold_time_comes_from_the_settings(session, cube):
    session.update_settings({"auto_capture_hold_ms": 2000})
    show(session, cube.face("F"), 2.0)  # held for 1.4 s of the 2 s
    assert session._scanned == {}
    show(session, cube.face("F"), 1.0)
    assert list(session._scanned) == ["F"]


def test_manual_mode_never_auto_captures(session, cube):
    session.handle_command("scan.auto", {"enabled": False})
    show(session, cube.face("F"), 2.0)
    assert session._scanned == {} and session._hold_progress == 0.0


def test_detection_events_report_the_hold(session, cube):
    show(session, cube.face("F"), 0.5)
    detection = [data for event, data in session.events if event == "detection"]
    assert detection and {"hold", "holdFace"} <= set(detection[-1])
