"""A SolveSession for tests, optionally with a cube and a known solution (no solver search)."""

from backend.core.cube import CubeState
from backend.core.moves import invert_sequence, parse_sequence
from backend.core.solver import Solution, SolverEngine
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from tests.storage import memory_stores


def new_session(publish_event=lambda event, data: None):
    return SolveSession(
        **memory_stores(),
        solver=SolverEngine(),
        logs=LogBus(),
        publish_event=publish_event,
        publish_frame=lambda jpeg: None,
    )


def with_solution(session, scramble="R U F"):
    """Give the session a scrambled cube and its 3-move solution, as if Solve had run."""
    moves_done = parse_sequence(scramble)
    cube = CubeState.solved().apply_sequence(moves_done)
    moves = invert_sequence(moves_done)
    states = [cube]
    for move in moves:
        states.append(states[-1].apply(move))
    session._cube = cube
    session._cube_source = "scramble"
    session._solution = Solution(moves, "Kociemba Two-Phase (C)", 1.5, cube.to_facelet_string(), cube, states)
    session._mode = "solution"
    return session
