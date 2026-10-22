"""Solve & Learn: the learner's cube, stages, hints, guided moves, and the session commands."""

import time

import pytest

from backend.ai.budget import RequestBudget
from backend.ai.lessons import load_lessons
from backend.ai.retrieval import LessonIndex
from backend.ai.service import AIService
from backend.core.beginner import current_stage, next_step, turn
from backend.core.cube import CubeState, random_scramble
from backend.services.learn import LearnError, LearnSession
from tests.sessions import new_session


def scrambled_cube(seed=5):
    return CubeState.solved().apply_sequence(random_scramble(25, seed=seed))


def started(cube=None):
    learn = LearnSession(cube or scrambled_cube())
    learn.set_ready()
    return learn


def follow_step(learn):
    """Do what "Show me" shows: every move of the next step (or turn the cube over)."""
    if learn.step().kind == "turn_over":
        learn.turn_over()
        return
    learn.show()
    for move in learn.to_dict()["step"]["notation"].split():
        learn.move(move)


def test_learning_needs_a_valid_cube_and_the_hold_step_first():
    facelets = CubeState.solved().facelets
    facelets["U"][0] = "Y"
    with pytest.raises(LearnError):
        LearnSession(CubeState(facelets))
    learn = LearnSession(scrambled_cube())
    assert learn.stage == 1 and learn.to_dict()["ready"] is False
    with pytest.raises(LearnError, match="hold the cube"):
        learn.move("R")


def test_the_cube_follows_every_move_and_undo():
    learn = started()
    before = learn.state
    learn.move("R")
    learn.move("U'")
    assert learn.state == turn(before, ["R", "U'"])
    data = learn.to_dict()
    assert data["lastMove"]["notation"] == "U'" and data["previous"] is not None and data["moveCount"] == 2
    learn.undo()
    assert learn.to_dict()["lastMove"] is None  # an undo is not animated as a turn
    learn.undo()
    assert learn.state == before and learn.to_dict()["version"] == 4
    with pytest.raises(LearnError, match="Nothing to undo"):
        learn.undo()


def test_hints_go_from_looking_to_the_algorithm_to_the_moves():
    learn = started()
    data = learn.to_dict()
    assert data["step"]["task"].startswith("Put the white-") and "moves" not in data["step"]
    assert learn.hint() == 1
    assert learn.to_dict()["hints"] == [{"level": 1, "text": learn.step().look, "source": "built-in", "model": None}]
    assert learn.allowed_sequences("hint") == []  # hint 1 may not name any moves
    assert learn.hint() == 2
    assert learn.to_dict()["hints"][1]["text"] == learn.step().how
    assert learn.hint() == 3  # the moves, and the app guides through them
    data = learn.to_dict()
    assert data["step"]["notation"] == " ".join(learn.step().moves)
    assert [m["notation"] for m in data["guide"]] == list(learn.step().moves)
    assert data["stages"][0]["hints"] == 3 and data["stages"][0]["alone"] is False


def test_guided_moves_finish_a_step_and_reset_the_hints():
    learn = started()
    stage = learn.stage
    follow_step(learn)
    data = learn.to_dict()
    assert data["guide"] == [] and data["hintLevel"] == 0 and data["hints"] == []
    assert learn.stage >= stage


def test_a_move_of_your_own_stops_the_guide():
    learn = started()
    learn.show()
    first = learn.step().moves[0]
    other = "D" if first[0] != "D" else "U"
    learn.move(other)
    assert learn.to_dict()["guide"] == []


def test_breaking_a_finished_stage_gets_a_note_and_undo_fixes_it():
    learn = started()
    while learn.stage == 1:
        follow_step(learn)
    assert learn.stage == 2 and learn.to_dict()["stages"][0]["done"] is True
    learn.move("F")  # takes a white cross edge out
    assert learn.stage == 1
    assert "broke your white cross" in learn.note
    learn.undo()
    assert learn.stage == 2 and learn.note is None


def test_turning_over_comes_after_the_white_layer():
    learn = started()
    with pytest.raises(LearnError, match="Keep holding"):
        learn.turn_over()
    while learn.stage < 3:
        follow_step(learn)
    assert learn.step().kind == "turn_over"
    assert learn.to_dict()["top"] == "W"
    learn.turn_over()
    assert learn.to_dict()["top"] == "Y" and learn.to_dict()["front"] == "G"
    assert learn.to_dict()["lastMove"] is None  # turning over is not a move: no turn animation


def turned_over():
    """A learner who has just finished the white layer and turned the cube over."""
    learn = started()
    while learn.step().kind != "turn_over":
        follow_step(learn)
    learn.turn_over()
    return learn


def test_after_turning_over_a_broken_white_layer_is_undone_not_turned_back():
    learn = turned_over()
    learn.move("D")  # D turns the white layer (now at the bottom): stages 1 and 2 break
    assert learn.stage <= 2 and "broke your white" in learn.note
    step = learn.step()
    assert step.kind == "moves" and step.moves == ("D'",)  # undo, never "turn it back over"
    assert step.task.startswith("Your white layer came apart")
    with pytest.raises(LearnError):
        learn.turn_over()
    follow_step(learn)
    assert learn.stage >= 3


def test_shown_moves_are_finished_before_anything_else():
    learn = turned_over()
    while learn.stage == 3 and learn.step().kind == "moves":
        learn.show()
        moves = list(learn.step().moves)
        learn.move(moves[0])  # mid-algorithm: the white layer may be broken for a moment
        assert [m["notation"] for m in learn.to_dict()["guideAll"]] == moves
        with pytest.raises(LearnError):
            learn.turn_over()  # never in the middle of shown moves
        for move in moves[1:]:
            learn.move(move)
        assert learn.to_dict()["guide"] == []
    assert learn.stage >= 4


def follow_guide(learn):
    """Press "Show me", then Done for each shown move until the guide stops. Returns (shown, made)."""
    learn.show()
    shown, made = len(learn.to_dict()["guideAll"]), 0
    while learn.to_dict()["guide"]:
        learn.move(learn.to_dict()["guide"][0]["notation"])
        made += 1
    return shown, made


def test_a_guide_stops_as_soon_as_its_stage_is_done():
    learn = started()
    while learn.stage == 1:
        follow_guide(learn)
    while learn.stage == 2:
        shown, made = follow_guide(learn)
    assert made == shown - 1  # the corner trick's last D isn't needed: the white layer is already done
    data = learn.to_dict()
    assert data["guide"] == [] and data["hintLevel"] == 0 and data["justDone"]["number"] == 2
    assert learn.step().kind == "turn_over"


def test_the_stage_bar_keeps_the_working_stage_in_the_middle_of_an_algorithm():
    learn = turned_over()
    learn.show()
    seen = []
    while learn.to_dict()["guide"]:
        learn.move(learn.to_dict()["guide"][0]["notation"])
        data = learn.to_dict()
        seen.append(data["stage"])
        if data["guide"]:  # still in the middle of the shown moves
            assert data["working"] == 3 and data["stages"][2]["current"] is True
            assert data["stages"][0]["done"] and data["stages"][1]["done"]
    assert min(seen) < 3  # the white layer did come apart for a moment


def test_undo_takes_a_finished_stage_back():
    learn = started()
    while learn.stage == 1:
        follow_guide(learn)
    assert learn.to_dict()["working"] == 2
    learn.undo()  # the move that finished the white cross
    data = learn.to_dict()
    assert learn.stage == 1 and data["working"] == 1 and data["stages"][0]["done"] is False


def test_following_the_app_solves_the_cube_and_counts_the_stages():
    learn = started(scrambled_cube(11))
    for _ in range(80):
        if learn.solved:
            break
        follow_step(learn)
    assert learn.solved and CubeState.from_color_string(learn.state).is_solved
    data = learn.to_dict()
    assert all(stage["done"] for stage in data["stages"]) and data["step"] is None
    stats = learn.stats()
    assert stats["moves"] > 50 and stats["stagesAlone"] == [] and len(stats["stagesWithHelp"]) == 7


def test_the_tutor_is_told_only_what_it_may_reveal():
    learn = started()
    assert "how" not in learn.facts("hint")["step"]
    learn.hint()
    learn.hint()
    facts = learn.facts("hint")
    assert facts["step"]["how"] and "moves" not in facts["step"]
    assert learn.facts("question")["stage"]["name"] == "White cross"


# ---- the session commands --------------------------------------------------------


def learn_session(cube=None, events=None):
    session = new_session(publish_event=(lambda e, d: events.append((e, d))) if events is not None else (lambda e, d: None))
    session._cube = cube or scrambled_cube()
    return session


def test_start_needs_a_valid_cube():
    session = new_session()
    assert session.handle_command("learn.start", {})["ok"] is False
    session = learn_session()
    assert session.handle_command("learn.start", {}) == {"ok": True, "stage": 1}
    learn = session.snapshot()["learn"]
    assert learn["stage"] == 1 and learn["ready"] is False and len(learn["stages"]) == 7


def test_commands_move_the_learners_cube_and_rejections_become_events():
    events = []
    session = learn_session(events=events)
    session.handle_command("learn.start", {})
    assert session.handle_command("learn.move", {"move": "R"})["ok"] is False
    assert events[-1] == ("learn:rejected", {"message": "First hold the cube as shown, then press the button below it"})
    session.handle_command("learn.ready", {})
    assert session.handle_command("learn.move", {"move": "R"})["ok"] is True
    assert session.snapshot()["learn"]["lastMove"]["notation"] == "R"
    assert session.handle_command("learn.move", {"move": "X"})["ok"] is False
    assert session.handle_command("learn.turnover", {})["ok"] is False


def wait_until(test, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not test():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_without_ai_hints_and_answers_come_from_the_app_and_the_lessons():
    session = learn_session()
    session._ai = AIService(None, RequestBudget(10, 100), None, lambda e, d: None,
                            off_reason="no Gemini API key is set", lessons=LessonIndex(load_lessons()))
    session.handle_command("learn.start", {})
    session.handle_command("learn.ready", {})
    session.handle_command("learn.hint", {})
    wait_until(lambda: not session.snapshot()["learn"]["tutorBusy"])
    learn = session.snapshot()["learn"]
    assert learn["hints"][0]["text"].startswith("Look at its white sticker")
    assert learn["hints"][0]["source"] == "fallback"
    session.handle_command("learn.ask", {"question": "How do I make the yellow cross?"})
    wait_until(lambda: session.snapshot()["learn"]["answer"] is not None)
    answer = session.snapshot()["learn"]["answer"]
    assert answer["message"].startswith("AI answers are off right now (no Gemini API key is set)")
    assert answer["citations"] == ["05-beginner-method#stage-4-the-yellow-cross"]
    assert answer["sources"][0]["section"] == "Stage 4: the yellow cross"
    assert session.handle_command("learn.ask", {"question": " "})["ok"] is False


def test_a_finished_solve_gets_a_recap_and_restart_starts_over():
    cube = scrambled_cube(2)
    session = learn_session(cube)
    session.handle_command("learn.start", {})
    session.handle_command("learn.ready", {})
    for _ in range(80):
        learn = session.snapshot()["learn"]
        if learn["solved"]:
            break
        if learn["step"]["kind"] == "turn_over":
            session.handle_command("learn.turnover", {})
            continue
        session.handle_command("learn.show", {})
        for move in session.snapshot()["learn"]["step"]["notation"].split():
            session.handle_command("learn.move", {"move": move})
    learn = session.snapshot()["learn"]
    assert learn["solved"] and learn["recap"]["message"].startswith("You solved your cube in")
    session.handle_command("learn.restart", {})
    learn = session.snapshot()["learn"]
    assert learn["moveCount"] == 0 and learn["cube"] == cube.facelets and learn["stage"] == current_stage(cube.to_color_string())
    session.handle_command("learn.exit", {})
    assert session.snapshot()["learn"] is None


def test_the_first_step_matches_the_core_method():
    cube = scrambled_cube(9)
    session = learn_session(cube)
    session.handle_command("learn.start", {})
    session.handle_command("learn.ready", {})
    session.handle_command("learn.show", {})
    step = next_step(cube.to_color_string())
    assert session.snapshot()["learn"]["step"]["notation"] == " ".join(step.moves)
