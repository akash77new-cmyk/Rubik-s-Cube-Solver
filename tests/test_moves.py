"""Move notation: parsing, inversion and the physical-turn expansion."""

import pytest

from backend.core.moves import (
    expand_for_physical_turns,
    invert_sequence,
    parse_sequence,
    sequence_to_string,
)

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
