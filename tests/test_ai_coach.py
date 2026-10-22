"""The RAG coach: grounded answers with checked citations, the fallback, and the commands."""

import threading

from backend.ai.agent import FINAL_ANSWER
from backend.ai.budget import RequestBudget
from backend.ai.coach import CoachContext, fallback_answer
from backend.ai.fake import HashEmbedder, ScriptedLLM, tool_call
from backend.ai.lessons import load_lessons
from backend.ai.llm import LLMRateLimited
from backend.ai.retrieval import LessonIndex
from backend.ai.service import AIService
from backend.ai.tracing import TraceStore
from backend.db import connect
from tests.sessions import new_session

NOTATION = "02-notation#clockwise-primes-and-doubles"
SEARCH = tool_call("search_lessons", query="What does R prime mean?")


def index():
    database = connect("sqlite://")
    lessons = LessonIndex(load_lessons(), database, HashEmbedder())
    lessons.sync()
    return lessons


def service(script=None, events=None):
    store = TraceStore(connect("sqlite://"))
    llm = ScriptedLLM(script) if script is not None else None
    publish = events if events is not None else (lambda e, d: None)
    ai = AIService(llm, RequestBudget(10, 100), store, publish, off_reason="no Gemini API key is set", lessons=index())
    return ai, store


def test_citations_must_come_from_this_runs_searches():
    context = CoachContext(index())
    context.search("What does R prime mean?")
    assert NOTATION in context.seen
    assert context.check_answer({"answer": "x", "citations": [NOTATION], "covered": True}) == []
    (problem,) = context.check_answer({"answer": "x", "citations": ["99-made-up#section"], "covered": True})
    assert "were not returned by search_lessons" in problem
    assert context.check_answer({"answer": "x", "citations": [], "covered": True}) == [
        "a covered answer must cite at least one passage"
    ]
    assert context.check_answer({"answer": "Not covered.", "citations": [], "covered": False}) == []


def test_the_built_in_answer_quotes_the_best_section():
    answer = fallback_answer(CoachContext(index()), "What does R prime mean?", "no Gemini API key is set")
    assert answer["citations"] == [NOTATION] and answer["covered"] is True
    assert answer["answer"].startswith("AI answers are off right now (no Gemini API key is set)")
    assert "anticlockwise" in answer["answer"]
    nothing = fallback_answer(CoachContext(index()), "zzzz qqqq", None)
    assert (nothing["covered"], nothing["citations"]) == (False, [])


def test_the_coach_searches_then_answers_with_citations():
    ai, store = service([SEARCH, tool_call(FINAL_ANSWER, answer="R' is anticlockwise.", citations=[NOTATION], covered=True)])
    payload = ai.coach_answer("What does R prime mean?")
    assert (payload["source"], payload["answer"], payload["citations"]) == ("scripted", "R' is anticlockwise.", [NOTATION])
    assert payload["sources"] == [
        {"id": NOTATION, "lesson": "02-notation", "lessonTitle": "Notation: how moves are written",
         "section": "Clockwise, primes and doubles"}
    ]
    assert payload["search"] == "vectors in Python"
    (run,) = store.recent()
    assert run["feature"] == "coach"


def test_a_made_up_citation_is_sent_back_and_corrected():
    ai, _ = service([
        SEARCH,
        tool_call(FINAL_ANSWER, answer="See lesson 99.", citations=["99-made-up#section"], covered=True),
        tool_call(FINAL_ANSWER, answer="R' is anticlockwise.", citations=[NOTATION], covered=True),
    ])
    payload = ai.coach_answer("What does R prime mean?")
    assert payload["citations"] == [NOTATION] and payload["requests"] == 3


def test_without_ai_or_on_errors_the_built_in_answer_is_used():
    off, _ = service(None)
    assert off.coach_answer("What does R prime mean?")["source"] == "fallback"
    failing, _ = service([LLMRateLimited("429")])
    payload = failing.coach_answer("What does R prime mean?")
    assert payload["reason"] == "Gemini's free limit is used up for now" and payload["citations"] == [NOTATION]


def test_the_session_commands():
    answered = threading.Event()
    seen = []

    def publish(event, data):
        seen.append((event, data))
        if event == "coach:answer":
            answered.set()

    ai, _ = service([SEARCH, tool_call(FINAL_ANSWER, answer="Anticlockwise.", citations=[NOTATION], covered=True)], publish)
    session = new_session(publish)
    session._ai = ai
    assert session.handle_command("lessons.list", {}) == {"ok": True, "count": 8}
    lessons = next(data for event, data in seen if event == "lessons:list")
    assert lessons[1]["sections"][1]["id"] == NOTATION
    assert session.handle_command("coach.ask", {"question": " "})["ok"] is False
    assert session.handle_command("coach.ask", {"question": "What does R prime mean?"})["ok"] is True
    assert answered.wait(5)
    assert session.snapshot()["ai"]["lessons"]["search"] == "vectors in Python"
