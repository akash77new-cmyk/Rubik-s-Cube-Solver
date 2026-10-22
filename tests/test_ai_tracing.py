"""Traces are saved in the database and read back for the AI page.

Runs on SQLite, and on PostgreSQL too when CUBE_TEST_POSTGRES_URL is set.
"""

from sqlalchemy import func, select

from backend.ai.fake import tool_call
from backend.ai.llm import ToolCall
from backend.ai.tracing import Trace, TraceStore
from backend.db.models import AIRunRow, AIStepRow


class Clock:
    def __init__(self, start=1_761_100_000.0):
        self.now = start

    def __call__(self):
        return self.now


def finished_trace(run_id, clock, question="How many moves?"):
    trace = Trace(run_id, "assistant", question, clock=clock)
    clock.now += 0.4
    trace.model_step(tool_call("get_solution"), 400)
    trace.tool_step(ToolCall("get_solution", {}), {"move_count": 20}, 2)
    clock.now += 0.6
    trace.model_step(tool_call("final_answer", answer="20 moves."), 600)
    trace.answer_step({"answer": "20 moves."})
    trace.finish("gemini", {"answer": "20 moves."}, "gemini-test", None)
    return trace


def test_a_trace_is_saved_and_read_back(open_db):
    clock = Clock()
    store = TraceStore(open_db())
    store.save(finished_trace("run1", clock))

    (run,) = store.recent()
    assert run["id"] == "run1" and run["question"] == "How many moves?"
    assert (run["source"], run["model"], run["reason"]) == ("gemini", "gemini-test", None)
    assert run["answer"] == {"answer": "20 moves."}
    assert (run["requestCount"], run["inputTokens"], run["durationMs"]) == (2, 200, 1000)
    assert abs(run["startedAt"] - 1_761_100_000.0) < 1e-3
    assert [(s["position"], s["kind"], s["name"]) for s in run["steps"]] == [
        (1, "model", "scripted"), (2, "tool", "get_solution"), (3, "model", "scripted"), (4, "answer", "final_answer"),
    ]
    assert run["steps"][1]["detail"] == {"args": {}, "result": {"move_count": 20}}
    assert run["steps"][0]["detail"]["toolCalls"] == [{"name": "get_solution", "args": {}}]


def test_newest_first_and_only_the_newest_are_kept(open_db):
    database = open_db()
    clock = Clock()
    store = TraceStore(database, max_runs=3)
    for number in range(5):
        clock.now += 60
        store.save(finished_trace(f"run{number}", clock))
    assert [run["id"] for run in store.recent()] == ["run4", "run3", "run2"]
    with database.transaction("count") as session:
        assert session.scalar(select(func.count()).select_from(AIRunRow)) == 3
        assert session.scalar(select(func.count()).select_from(AIStepRow)) == 12  # old steps deleted too


def test_request_times_refill_the_budget_after_a_restart(open_db):
    clock = Clock()
    store = TraceStore(open_db())
    store.save(finished_trace("old", clock))
    clock.now += 2 * 24 * 3600
    store.save(finished_trace("new", clock))
    times = store.request_times(since=clock.now - 24 * 3600)
    assert len(times) == 2  # the two model requests of the new run; tool steps don't count


def test_no_runs_yet(open_db):
    assert TraceStore(open_db()).recent() == []
