"""Cube model: move simulation, validation and serialisation."""

import pytest

from backend.core.cube import CubeState, random_scramble
from backend.core.moves import invert_sequence


def test_200_scrambles_then_inverse_return_to_solved():
    for seed in range(200):
        scramble = random_scramble(25, seed=seed)
        state = CubeState.solved().apply_sequence(scramble)
        assert not state.is_solved, f"seed {seed} produced a solved cube"
        state = state.apply_sequence(invert_sequence(scramble))
        assert state.is_solved, f"seed {seed} did not return to solved"


@pytest.mark.parametrize("face", list("URFDLB"))
def test_four_turns_of_a_face_is_the_identity(face):
    state = CubeState.solved()
    for _ in range(4):
        state = state.apply(face)
    assert state.is_solved


def test_sexy_move_six_times_is_the_identity():
    state = CubeState.solved().apply_sequence("R U R' U' " * 6)
    assert state.is_solved


def test_colour_count_violation_fails_validation():
    facelets = CubeState.solved().facelets
    facelets["U"][0] = "R"  # ten reds, eight whites
    result = CubeState(facelets).validate()
    assert not result.ok
    assert result.errors


def test_colour_string_round_trip():
    state = CubeState.solved().apply_sequence(random_scramble(25, seed=1))
    assert CubeState.from_color_string(state.to_color_string()) == state


def test_solved_cube_has_54_solved_stickers():
    assert CubeState.solved().solved_sticker_count() == 54
