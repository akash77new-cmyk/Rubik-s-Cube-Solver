"""The AI Tutor: its move and citation checks, the agent runs, and the built-in answers."""

from backend.ai.agent import FINAL_ANSWER
from backend.ai.budget import RequestBudget
from backend.ai.fake import HashEmbedder, ScriptedLLM, tool_call
from backend.ai.lessons import load_lessons
from backend.ai.llm import LLMRateLimited
from backend.ai.retrieval import LessonIndex
from backend.ai.service import AIService
from backend.ai.tracing import TraceStore
from backend.ai.tutor import TutorContext, move_runs, recap_text
from backend.core.cube import CubeState, random_scramble
from backend.db import connect
from backend.services.learn import LearnSession

YELLOW_CROSS = "05-beginner-method#stage-4-the-yellow-cross"


def lessons():
    index = LessonIndex(load_lessons(), connect("sqlite://"), HashEmbedder())
    index.sync()
    return index


def learner(hints=0):
    learn = LearnSession(CubeState.solved().apply_sequence(random_scramble(25, seed=5)))
    learn.set_ready()
    for _ in range(hints):
        learn.hint()
    return learn


def context(kind="hint", hints=1, question=""):
    learn = learner(hints)
    return TutorContext(kind, learn.facts(kind), learn.allowed_sequences(kind), lessons(), question), learn


def service(script=None):
    store = TraceStore(connect("sqlite://"))
    llm = ScriptedLLM(script) if script is not None else None
    ai = AIService(llm, RequestBudget(10, 100), store, lambda e, d: None, off_reason="no Gemini API key is set",
                   lessons=lessons())
    return ai, store


def test_move_sequences_are_found_in_text():
    assert move_runs("Do R U R' U' four times.") == [["R", "U", "R'", "U'"]]
    assert move_runs("Use R, U, R’, U’") == [["R", "U", "R'", "U'"]]
    assert move_runs("Turn the U layer, then the R side.") == []  # single letters are not sequences
    assert move_runs("F2L comes after the cross") == []


def test_hint_1_may_not_contain_moves():
    ctx, _ = context("hint", hints=1)
    assert ctx.check_answer({"message": "Look where its white sticker points.", "citations": []}) == []
    (problem,) = ctx.check_answer({"message": "Do F U' R U.", "citations": []})
    assert "must not contain moves" in problem


def test_hint_2_may_write_the_algorithm_but_not_made_up_moves():
    learn = learner(hints=0)
    while learn.step().algorithm is None:  # stage 1 has no algorithm: go to a stage that has one
        if learn.step().kind == "turn_over":
            learn.turn_over()
            continue
        learn.show()
        for move in learn.step().moves:
            learn.move(move)
    learn.hint()
    learn.hint()
    ctx = TutorContext("hint", learn.facts("hint"), learn.allowed_sequences("hint"), None)
    algorithm = " ".join(learn.step().algorithm_moves)
    assert ctx.check_answer({"message": f"Use the corner trick: {algorithm}.", "citations": []}) == []
    (problem,) = ctx.check_answer({"message": "Try L2 B2 D2 instead.", "citations": []})
    assert "don't come from the app" in problem


def test_citations_must_come_from_this_runs_searches_and_passages_may_be_quoted():
    ctx, _ = context("question", hints=0, question="How do I make the yellow cross?")
    (problem,) = ctx.check_answer({"message": "See the lesson.", "citations": [YELLOW_CROSS]})
    assert "were not returned by search_lessons" in problem
    ctx.search("How do I make the yellow cross?")
    assert ctx.check_answer({"message": "Do F R U R' U' F' with the L at the back-left.", "citations": [YELLOW_CROSS]}) == []


def test_a_hint_takes_one_request():
    ai, store = service([tool_call(FINAL_ANSWER, message="Find the white sticker first: which way does it point?", citations=[])])
    ctx, _ = context("hint", hints=1)
    payload = ai.tutor_answer(ctx)
    assert payload["source"] == "scripted" and payload["requests"] == 1
    assert payload["message"].startswith("Find the white sticker")
    (trace,) = store.recent(1)
    assert trace["feature"] == "tutor"


def test_a_question_searches_the_lessons_and_cites_them():
    script = [
        tool_call("search_lessons", query="yellow cross"),
        tool_call(FINAL_ANSWER, message="Hold the L at the back-left and do F R U R' U' F'.", citations=[YELLOW_CROSS]),
    ]
    ai, _ = service(script)
    ctx, _ = context("question", hints=0, question="How do I make the yellow cross?")
    payload = ai.tutor_answer(ctx)
    assert payload["citations"] == [YELLOW_CROSS] and payload["sources"][0]["section"] == "Stage 4: the yellow cross"


def test_made_up_moves_go_back_to_the_model():
    script = [
        tool_call(FINAL_ANSWER, message="Just do R2 L2 B2.", citations=[]),
        tool_call(FINAL_ANSWER, message="Look at where the white sticker of that edge points.", citations=[]),
    ]
    ai, _ = service(script)
    ctx, _ = context("hint", hints=1)
    payload = ai.tutor_answer(ctx)
    assert payload["message"].startswith("Look at where") and payload["requests"] == 2


def test_without_ai_the_built_in_texts_answer():
    ai, _ = service([LLMRateLimited("quota")])
    ctx, learn = context("hint", hints=2)
    payload = ai.tutor_answer(ctx)
    assert payload["source"] == "fallback" and payload["message"] == learn.step().how
    assert payload["reason"] == "Gemini's free limit is used up for now"
    off, _ = service()
    question, _ = context("question", hints=0, question="How do I make the yellow cross?")
    answer = off.tutor_answer(question)
    assert answer["citations"] == [YELLOW_CROSS]


def test_the_built_in_recap():
    text = recap_text({"moves": 120, "seconds": 600, "stagesAlone": ["White cross"],
                       "stagesWithHelp": ["Yellow face", "Yellow edges"], "practise": "Yellow face"})
    assert text == ("You solved your cube in 120 moves and about 10 min. You did 1 of 7 stages without help. "
                    "Practise the yellow face stage next, until you can do it without hints.")
