"""The beginner method (Phase 8): stage checks, steps and the full solve, by simulation."""

import random

import pytest

from backend.core import beginner
from backend.core.beginner import (
    ALGORITHMS,
    CROSS_CASES,
    MOVE_NAMES,
    STAGES,
    TURN_OVER_FACES,
    current_stage,
    next_step,
    parse_names,
    solve_all,
    turn,
    turn_over,
)
from backend.core.cube import CubeState, random_scramble
from backend.core.moves import Move, invert_sequence

SOLVED = CubeState.solved().to_color_string()


def scrambled(seed: int) -> str:
    return CubeState.solved().apply_sequence(random_scramble(25, seed=seed)).to_color_string()


def test_fast_turns_match_the_cube_model():
    rng = random.Random(1)
    cube, state = CubeState.solved(), SOLVED
    for _ in range(300):
        name = rng.choice(MOVE_NAMES)
        cube, state = cube.apply(name), turn(state, [name])
        assert cube.to_color_string() == state


def test_turning_over_swaps_top_and_bottom_and_left_and_right():
    assert TURN_OVER_FACES == {"U": "D", "D": "U", "R": "L", "L": "R", "F": "F", "B": "B"}
    flipped = turn_over(SOLVED)
    assert flipped == "Y" * 9 + "O" * 9 + "G" * 9 + "W" * 9 + "R" * 9 + "B" * 9
    state = scrambled(3)
    for name in MOVE_NAMES:  # a move before turning over = the mapped move after it
        assert turn_over(turn(state, [name])) == turn(turn_over(state), [TURN_OVER_FACES[name[0]] + name[1:]])
    assert turn_over(turn_over(state)) == state


def test_quarter_views_relabel_moves_exactly():
    state = scrambled(4)
    for times in range(4):
        for name in MOVE_NAMES:
            view_then_move = turn(beginner._rotate_quarter(state, times), [name])
            move_then_view = beginner._rotate_quarter(turn(state, beginner._relabel([name], times)), times)
            assert view_then_move == move_then_view


def test_stage_checks_on_simple_cubes():
    assert current_stage(SOLVED) == 8
    assert current_stage(turn_over(SOLVED)) == 8  # solved is solved, whichever way up
    assert current_stage(turn(SOLVED, ["U"])) == 1  # every white edge is out of place
    assert current_stage(turn(SOLVED, ["D"])) == 6  # D is the yellow layer: only its pieces moved
    yellow_up = turn_over(SOLVED)
    insert = parse_names(ALGORITHMS["right"][1])
    undo = [move.notation for move in invert_sequence(Move.parse(m) for m in insert)]
    assert current_stage(turn(yellow_up, undo)) == 3  # one middle edge taken out
    sune = parse_names(ALGORITHMS["sune"][1])
    assert current_stage(turn(yellow_up, sune)) == 5  # only the top corners are twisted


@pytest.mark.parametrize("case", sorted(CROSS_CASES))
def test_every_white_cross_case(case):
    """Each case: undo its moves from solved to set it up, then its moves must solve it."""
    moves = list(CROSS_CASES[case])
    setup = [move.notation for move in invert_sequence(Move.parse(m) for m in moves)]
    state = turn(SOLVED, setup)
    assert beginner._edge_place(state, ("W", "G")) == case
    after = turn(state, moves)
    assert all(beginner.is_home(after, beginner.find_piece(after, c)) for c in beginner.white_edges(after))


def test_the_corner_trick_takes_1_3_or_5_tries_from_under_the_corner():
    trick = parse_names(ALGORITHMS["corner"][1])
    tries = []
    for k in range(1, 6):
        state = turn(SOLVED, trick * k)
        slot = beginner.find_piece(state, ("W", "G", "R"))
        if beginner.SLOT_NAMES[slot] == "DFR":
            tries.append(6 - k)
    assert sorted(tries) == [1, 3, 5]


def test_a_cube_held_the_wrong_way_up_asks_to_turn_it_over():
    state = turn(SOLVED, ["D", "R", "U"])  # white cross broken, white on top: no turning over
    assert next_step(state).kind == "moves"
    step = next_step(turn_over(state))
    assert step.kind == "turn_over" and step.moves == ()
    assert "white" in step.task


def test_a_step_names_the_piece_and_its_place():
    step = next_step(turn(SOLVED, ["F2"]))  # the white-green edge is at the bottom front
    assert step.stage == 1
    assert step.task.startswith("Put the white-green edge on top")
    assert "bottom layer, at the front" in step.task
    assert step.moves == ("F2",)
    data = step.to_dict()
    assert data["notation"] == "F2" and data["moves"][0]["instruction"]
    assert set(data["focus"]) == {"D1", "F7"}


@pytest.mark.parametrize("seed", range(40))
def test_the_method_solves_random_cubes_stage_by_stage(seed):
    state = scrambled(seed)
    actions, stages = solve_all(state)
    assert stages == sorted(stages)  # the stages come in order, never back
    assert actions.count("turn_over") == 1  # white on top for stages 1-2, yellow after
    for action in actions:
        state = turn_over(state) if action == "turn_over" else turn(state, [action])
    assert current_stage(state) == 8 and CubeState.from_color_string(state).is_solved


def test_each_yellow_stage_needs_at_most_three_algorithms():
    for seed in range(40, 70):
        state = scrambled(seed)
        counts = {}
        while (step := next_step(state)) is not None:
            if step.kind == "turn_over":
                state = turn_over(state)
                continue
            if step.algorithm:
                counts[step.stage] = counts.get(step.stage, 0) + 1
            state = turn(state, step.moves)
        assert all(counts.get(stage, 0) <= 3 for stage in (4, 5, 6, 7)), counts


def test_the_stages_link_to_lesson_sections():
    assert [stage.number for stage in STAGES] == list(range(1, 8))
    assert all(stage.lesson.startswith("05-beginner-method#stage-") for stage in STAGES)
