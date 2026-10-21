"""Solution playback: the hold-the-cube step before move 1, stepping and restarting.

A known 3-move solution is set up directly, so these tests don't run the solver.
"""

import numpy as np
import pytest

from backend.core.cube import CubeState
from backend.core.moves import invert_sequence, parse_sequence
from backend.core.solver import Solution, SolverEngine
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from tests.storage import memory_stores

SCRAMBLE = parse_sequence("R U F")  # so the solution is F' U' R'


@pytest.fixture
def session(tmp_path):
    s = SolveSession(
        **memory_stores(),
        solver=SolverEngine(),
        logs=LogBus(),
        publish_event=lambda event, data: None,
        publish_frame=lambda jpeg: None,
    )
    cube = CubeState.solved().apply_sequence(SCRAMBLE)
    moves = invert_sequence(SCRAMBLE)
    states = [cube]
    for move in moves:
        states.append(states[-1].apply(move))
    s._cube = cube
    s._solution = Solution(moves, "test", 0.0, cube.to_facelet_string(), cube, states)
    s._solve_id = "test"
    s._mode = "solution"
    return s


def step(session, action, **payload):
    session.handle_command(f"playback.{action}", payload)
    return session.snapshot()["playback"]


def test_the_hold_step_comes_before_move_one(session):
    state = session.snapshot()["playback"]
    assert not state["ready"] and state["index"] == 0
    state = step(session, "next")  # "I'm holding it like this"
    assert state["ready"] and state["index"] == 0 and state["current"]["notation"] == "F'"


def test_previous_from_move_one_goes_back_to_the_hold_step(session):
    step(session, "next")  # hold step done
    step(session, "next")  # move 1 done
    state = step(session, "prev")
    assert state["ready"] and state["index"] == 0
    state = step(session, "prev")
    assert not state["ready"] and state["index"] == 0


def test_hold_step_then_every_move_solves_the_cube(session):
    step(session, "next")
    for _ in range(3):
        state = step(session, "next")
    assert state["completed"] and CubeState(state["cube"]).is_solved


def test_jumping_to_a_move_skips_the_hold_step_and_restart_brings_it_back(session):
    state = step(session, "seek", index=2)
    assert state["ready"] and state["index"] == 2
    state = step(session, "restart")
    assert not state["ready"] and state["index"] == 0


def test_auto_play_shows_each_move_for_8_seconds_whatever_the_animation_speed(session):
    assert session._autoplay_seconds() == 8.0
    session.update_settings({"animation_speed": 0.25})  # a slow 3D animation...
    assert session._autoplay_seconds() == 8.0  # ...doesn't stretch the time per move


def test_auto_play_starts_by_showing_move_one(session):
    state = step(session, "play")
    assert state["ready"] and state["playing"] and state["index"] == 0
    step(session, "pause")


def test_camera_guidance_shows_how_to_hold_the_cube_first(session, monkeypatch):
    shown = []
    monkeypatch.setattr(session.overlay, "draw_hold_prompt", lambda frame, front, top: shown.append((front, top)))
    step(session, "execute")
    frame = np.zeros((720, 960, 3), np.uint8)
    session._render_scene(frame, session.detector.detect(frame), session._settings.current)
    assert shown == [("G", "W")]  # green (front centre) facing you, white (top centre) on top
    step(session, "next")
    session._render_scene(frame, session.detector.detect(frame), session._settings.current)
    assert len(shown) == 1  # now the first move is drawn instead
