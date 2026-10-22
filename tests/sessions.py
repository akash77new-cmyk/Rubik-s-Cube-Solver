"""SolveSessions for tests: with a known solution (no solver search), or just after a camera scan."""

from backend.core.cube import FACE_ORDER, CubeState
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


#: A short scramble the repair tests use as "the real cube".
SCRAMBLE = "R U R' U' F2 D L2 B"


def real_cube():
    return CubeState.solved().apply_sequence(parse_sequence(SCRAMBLE))


def misread(cube, changes):
    """The cube as a camera that misread some stickers would report it: {(face, index): colour}."""
    facelets = cube.facelets
    for (face, index), color in changes.items():
        facelets[face][index] = color
    return CubeState(facelets)


def readings_for(cube, doubtful=None):
    """Camera readings like the scanner keeps them: sure of every sticker, except the
    doubtful ones, given as {(face, index): (read_as, second_guess, confidence, second_confidence)}."""
    doubtful = doubtful or {}
    readings = {}
    for face in FACE_ORDER:
        rows = []
        for index, color in enumerate(cube.face(face)):
            read_as, second, confidence, second_confidence = doubtful.get(
                (face, index), (color, "W" if color != "W" else "Y", 0.9, 0.2)
            )
            rows.append({
                "index": index,
                "color": read_as,
                "confidence": confidence,
                "alternatives": [
                    {"color": read_as, "confidence": confidence, "inRange": True},
                    {"color": second, "confidence": second_confidence, "inRange": second_confidence > 0.5},
                ],
                "uncertain": "two_ranges" if second_confidence > 0.5 else None,
            })
        readings[face] = rows
    return readings


def scanned_session(cube, doubtful=None, ai=None, publish_event=lambda event, data: None):
    """A session that has just captured all six faces of ``cube`` with the camera."""
    session = new_session(publish_event)
    session._ai = ai
    readings = readings_for(cube, doubtful)
    session._scanned = {
        face: {"colors": cube.face(face), "confidence": 0.9, "minConfidence": 0.5, "timestamp": 0.0,
               "auto": False, "stickers": readings[face]}
        for face in FACE_ORDER
    }
    session._finish_scan()
    return session
