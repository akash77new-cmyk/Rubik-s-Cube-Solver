"""The Cube Assistant's tools read the real session, and its fallback states the same facts."""

from backend.ai.assistant import TOOL_NAMES, SnapshotContext, build_tools, fallback_answer
from tests.sessions import new_session, with_solution


def call(session, name, **args):
    tools = build_tools(SnapshotContext(session.snapshot))
    return tools.call(name, args, TOOL_NAMES)


def test_an_empty_session():
    session = new_session()
    assert call(session, "get_cube_state")["has_cube"] is False
    assert "Scanner" in call(session, "get_cube_state")["hint"]
    assert call(session, "get_solution")["has_solution"] is False
    scan = call(session, "get_scan_progress")
    assert scan["sides_captured"] == 0 and len(scan["sides"]) == 6
    assert scan["next_instruction"] == "Green facing the camera, white on top"
    assert call(session, "get_solve_stats")["total_solves"] == 0


def test_cube_and_solution_facts():
    session = with_solution(new_session())
    cube = call(session, "get_cube_state")
    assert (cube["has_cube"], cube["source"], cube["valid"], cube["is_solved"]) == (True, "scramble", True, False)
    solution = call(session, "get_solution")
    assert (solution["move_count"], solution["moves"], solution["current_step"]) == (3, "F' U' R'", 0)
    move = call(session, "explain_move", step=1)
    assert (move["notation"], move["of"]) == ("F'", 3)
    assert move["instruction"]  # the same plain-English sentence the Solution page shows


def test_bad_steps_are_reported_to_the_model():
    session = with_solution(new_session())
    assert call(session, "explain_move", step=9) == {"error": "There is no step 9: the solution has 3 moves."}
    assert call(session, "explain_move", step="2")["error"].startswith("Invalid arguments")


def test_an_invalid_cube_lists_its_problems():
    session = new_session()
    session.handle_command("cube.reset", {})  # a solved cube: the white face is all white
    session.handle_command("cube.sticker", {"face": "U", "index": 0, "color": "Y"})  # now 10 yellows
    cube = call(session, "get_cube_state")
    assert cube["valid"] is False
    assert cube["problems"] and {"code", "message"} == set(cube["problems"][0])


def test_the_fallback_states_the_same_facts():
    empty = fallback_answer(SnapshotContext(new_session().snapshot), "no Gemini API key is set")
    assert empty["answer"].startswith("AI answers are off right now (no Gemini API key is set)")
    assert "There is no cube yet" in empty["answer"]

    solved = fallback_answer(SnapshotContext(with_solution(new_session()).snapshot), "x")
    assert "valid and ready to solve" in solved["answer"]
    assert "The solution has 3 moves: F' U' R'." in solved["answer"]
    assert solved["suggestions"] == []
