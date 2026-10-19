"""Kociemba solver: every solution must really solve the cube when replayed."""

import pytest

from backend.core.cube import CubeState, random_scramble
from backend.core.solver import SolverEngine

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def solver() -> SolverEngine:
    engine = SolverEngine()
    if not engine.warm_up(600):
        pytest.fail(f"solver never became ready: {engine.status()['message']}")
    return engine


@pytest.mark.parametrize("length", [6, 12, 18, 25])
def test_solution_replays_to_solved(solver, length):
    cube = CubeState.solved().apply_sequence(random_scramble(length, seed=length))
    solution = solver.solve(cube)

    assert cube.apply_sequence(solution.moves).is_solved
    assert solution.move_count <= 22
    assert len(solution.states) == solution.move_count + 1
