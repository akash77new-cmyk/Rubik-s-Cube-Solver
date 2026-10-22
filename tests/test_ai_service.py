"""The AI service: answers in the background, traces every run, falls back when it must."""

import subprocess
import sys
import threading
import time

from backend.ai.agent import FINAL_ANSWER
from backend.ai.assistant import SnapshotContext
from backend.ai.budget import RequestBudget
from backend.ai.fake import ScriptedLLM, tool_call
from backend.ai.llm import LLMRateLimited
from backend.ai.service import AIConfig, AIService
from backend.ai.tracing import TraceStore
from backend.config import PROJECT_ROOT
from backend.db import StorageError, connect
from tests.sessions import new_session, with_solution


class Events:
    """Collects published events."""

    def __init__(self):
        self.items = []
        self.answered = threading.Event()

    def __call__(self, event, data):
        self.items.append((event, data))
        if event == "ai:answer":
            self.answered.set()

    def of(self, event):
        return [data for name, data in self.items if name == event]


def service(script=None, per_day=100, store=True):
    events = Events()
    llm = ScriptedLLM(script) if script is not None else None
    trace_store = TraceStore(connect("sqlite://")) if store else None
    ai = AIService(llm, RequestBudget(10, per_day), trace_store, events, off_reason="no Gemini API key is set")
    return ai, events, trace_store


def context():
    return SnapshotContext(with_solution(new_session()).snapshot)


def test_a_model_answer_is_published_and_traced():
    ai, events, store = service([tool_call("get_solution"), tool_call(FINAL_ANSWER, answer="3 moves.", suggestions=["Step 1?"])])
    payload = ai.answer("How many moves?", context())
    assert (payload["answer"], payload["suggestions"], payload["source"]) == ("3 moves.", ["Step 1?"], "scripted")
    assert (payload["requests"], payload["toolCalls"], payload["reason"]) == (2, 1, None)
    assert events.of("ai:answer") == [payload]
    assert [p["tool"] for p in events.of("ai:progress")] == [None, "get_solution"]
    (run,) = store.recent()
    assert run["source"] == "scripted" and len(run["steps"]) == 4


def test_without_a_key_the_built_in_answer_is_used_and_traced():
    ai, events, store = service(script=None)
    payload = ai.answer("How many moves?", context())
    assert payload["source"] == "fallback" and payload["reason"] == "no Gemini API key is set"
    assert "The solution has 3 moves" in payload["answer"]
    (run,) = store.recent()
    assert run["steps"][0]["kind"] == "error" and run["steps"][0]["name"] == "ai_off"
    assert ai.status()["enabled"] is False and ai.status()["offReason"] == "no Gemini API key is set"


def test_a_model_error_falls_back_with_a_plain_reason():
    ai, events, store = service([LLMRateLimited("429 from Google")])
    payload = ai.answer("How many moves?", context())
    assert payload["source"] == "fallback"
    assert payload["reason"] == "Gemini's free limit is used up for now"
    assert ai.status()["lastError"] == "429 from Google"


def test_the_budget_stops_requests_before_google_does():
    ai, events, store = service([tool_call("get_solution"), tool_call(FINAL_ANSWER, answer="x")], per_day=1)
    payload = ai.answer("How many moves?", context())
    assert payload["source"] == "fallback" and "daily limit of 1" in payload["reason"]
    assert payload["requests"] == 1  # the second request was never sent


def test_no_answer_within_the_step_limit_falls_back():
    ai, events, store = service([tool_call("get_solution")] * 5)
    payload = ai.answer("How many moves?", context())
    assert payload["reason"] == "the AI didn't reach an answer in time" and payload["requests"] == 5


def test_a_trace_that_cannot_be_saved_does_not_lose_the_answer(monkeypatch):
    ai, events, store = service([tool_call(FINAL_ANSWER, answer="Hi.")])

    def broken(trace):
        raise StorageError("Could not save the AI trace: connection refused")

    monkeypatch.setattr(store, "save", broken)
    assert ai.answer("Hello?", context())["answer"] == "Hi."


def test_ask_checks_the_question_and_answers_in_the_background():
    release = threading.Event()

    def slow_answer(request):
        release.wait(5)  # the model "thinks" until the test lets it go
        return tool_call(FINAL_ANSWER, answer="Done.")

    ai, events, store = service([slow_answer])
    assert ai.ask("   ", context()) == {"ok": False, "error": "Type a question first."}
    assert ai.ask("x" * 301, context())["error"] == "Keep questions under 300 characters."

    started = ai.ask("  How   many moves? ", context())
    assert started["ok"] is True and ai.status()["busy"] is True
    assert ai.ask("Another one?", context())["error"] == "The assistant is still answering the last question."
    release.set()
    assert events.answered.wait(5)
    (answer,) = events.of("ai:answer")
    assert answer["question"] == "How many moves?" and answer["runId"] == started["runId"]
    for _ in range(100):  # the worker clears "busy" right after publishing the answer
        if not ai.status()["busy"]:
            break
        time.sleep(0.01)
    assert ai.status()["busy"] is False


def test_create_turns_ai_off_without_a_key_and_counts_old_requests():
    store = TraceStore(connect("sqlite://"))
    earlier = AIService(ScriptedLLM([tool_call(FINAL_ANSWER, answer="Hi.")]), RequestBudget(10, 100), store, Events())
    earlier.answer("Hello?", context())  # one model request, traced in the store

    ai = AIService.create(AIConfig(api_key="", model="gemini-test"), store, publish=lambda e, d: None)
    status = ai.status()
    assert status["enabled"] is False and status["budget"]["usedToday"] == 1  # the earlier request
    on = AIService.create(AIConfig(api_key="KEY", model="gemini-test"), None, publish=lambda e, d: None)
    assert (on.status()["provider"], on.status()["model"]) == ("gemini", "gemini-test")


def test_the_session_commands():
    events = Events()
    ai = AIService(
        ScriptedLLM([tool_call(FINAL_ANSWER, answer="3 moves.")]), RequestBudget(10, 100),
        TraceStore(connect("sqlite://")), events,
    )
    session = with_solution(new_session())
    session._ai = ai
    session._publish_event = events

    assert session.handle_command("ai.ask", {"question": ""})["ok"] is False
    assert events.of("ai:rejected") == [{"message": "Type a question first."}]
    assert session.handle_command("ai.ask", {"question": "How many moves?"})["ok"] is True
    assert events.answered.wait(5)
    assert session.snapshot()["ai"]["enabled"] is True
    session.handle_command("ai.traces", {})
    (traces,) = events.of("ai:traces")
    assert traces[0]["question"] == "How many moves?"


def test_the_web_server_never_loads_the_ai_layer_or_the_database():
    """The web server is a pure relay: only the engine process talks to Gemini and the database."""
    code = (
        "import sys, backend.server.app; "
        "print(sorted(m for m in sys.modules if m.startswith(('backend.ai', 'backend.db', 'sqlalchemy'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"
