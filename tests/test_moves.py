"""Move notation: parsing, inversion, the physical-turn expansion and the
plain-English instructions."""

import pytest

from backend.core.cube import FACE_ORDER, CubeState
from backend.core.moves import (
    INSTRUCTIONS,
    Move,
    expand_for_physical_turns,
    invert_sequence,
    parse_sequence,
    sequence_to_string,
)

SOLVED = CubeState.solved()
CENTER = {face: SOLVED.face(face)[4] for face in FACE_ORDER}
ALL_MOVES = [face + modifier for face in "URFDLB" for modifier in ("", "'", "2")]

# A person cannot see the back face, so B turns become "turn the cube, turn F,
# turn it back"; half turns become two quarter turns (one arrow at a time).
PHYSICAL_EXPANSION = {
    "B": ["TURN_BACK", "F", "TURN_BACK"],
    "B'": ["TURN_BACK", "F'", "TURN_BACK"],
    "B2": ["TURN_BACK", "F", "F", "TURN_BACK"],
    "R2": ["R", "R"],
    "U'": ["U'"],
}


@pytest.mark.parametrize("notation, expected", PHYSICAL_EXPANSION.items())
def test_physical_expansion(notation, expected):
    assert expand_for_physical_turns(parse_sequence(notation)) == expected


def test_inverting_twice_gives_the_original():
    moves = parse_sequence("R U' F2 D L' B2 U R2")
    assert invert_sequence(invert_sequence(moves)) == moves


def test_parse_then_format_round_trip():
    assert sequence_to_string(parse_sequence("R U' F2")) == "R U' F2"


@pytest.mark.parametrize("notation", [m for m in ALL_MOVES if not m.endswith("2")])
def test_each_arrow_matches_what_the_cube_model_does(notation):
    """Hold the cube with the front facing you: the arrow must be what really happens."""
    move = Move.parse(notation)
    after = SOLVED.apply(notation)
    if move.face in ("U", "D", "R", "L"):
        # The layer's front stickers travel left / right / up / down, onto that face.
        target = {"left": "L", "right": "R", "up": "U", "down": "D"}[move.arrow]
        assert after.face(target).count(CENTER["F"]) == 3
    else:
        # F, and B after turning the cube around, are turned while looking at them:
        # clockwise lifts the stickers on your left up to the top. Facing F, your left
        # is the L side; facing B, it is the R side.
        left, right = ("L", "R") if move.face == "F" else ("R", "L")
        lifted = left if move.arrow == "clockwise" else right
        assert after.face("U").count(CENTER[lifted]) == 3


@pytest.mark.parametrize("notation", ALL_MOVES)
def test_each_instruction_says_the_same_as_its_arrow(notation):
    move = Move.parse(notation)
    text = move.instruction
    assert text == INSTRUCTIONS[notation] and text.endswith(".")
    if move.modifier == "2":
        assert "twice" in text
    elif move.face in ("U", "D", "R", "L"):
        opposite = {"left": "right", "right": "left", "up": "down", "down": "up"}[move.arrow]
        assert move.arrow in text and opposite not in text
    else:
        assert move.arrow in text
        assert ("counter" in text) == (move.arrow == "counter-clockwise")
    if move.face == "B":  # matches the physical steps: turn around, turn, turn back
        assert "turn the cube back" in text


def test_move_info_for_the_ui_carries_arrow_and_instruction():
    info = Move.parse("R'").to_dict()
    assert info["arrow"] == "down"
    assert info["instruction"] == "Turn the right side down, towards you."
    assert len(INSTRUCTIONS) == 18
