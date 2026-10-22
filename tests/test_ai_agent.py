"""The agent loop: allowlist, validated arguments, structured answer, limits, tracing."""

import pytest

from backend.ai.agent import FINAL_ANSWER, AgentStopped, AgentTask, run_agent
from backend.ai.fake import ScriptedLLM, text_reply, tool_call, tool_calls
from backend.ai.llm import LLMRateLimited
from backend.ai.tools import NO_ARGS, Tool, ToolRegistry
from backend.ai.tracing import Trace

ANSWER = {
    "type": "object",
    "properties": {"answer": {"type": "string", "minLength": 1, "maxLength": 50}},
    "required": ["answer"],
    "additionalProperties": False,
}
STEP = {
    "type": "object",
    "properties": {"step": {"type": "integer", "minimum": 1, "maximum": 3}},
    "required": ["step"],
    "additionalProperties": False,
}


def registry():
    return ToolRegistry(
        [
            Tool("get_solution", "The solution.", NO_ARGS, lambda args: {"moves": "R U F", "move_count": 3}),
            Tool("explain_move", "One move.", STEP, lambda args: {"step": args["step"], "notation": "RUF"[args["step"] - 1]}),
            Tool("broken", "Always fails.", NO_ARGS, lambda args: 1 / 0),
            Tool("secret", "Not for this task.", NO_ARGS, lambda args: {"secret": 42}),
        ]
    )


def task(**overrides):
    values = dict(
        system_prompt="Be brief.",
        question="How many moves?",
        tools=registry(),
        allowed_tools=["get_solution", "explain_move", "broken"],
        answer_schema=ANSWER,
        max_steps=4,
    )
    values.update(overrides)
    return AgentTask(**values)


def tool_results(request):
    """The tool results the app sent in a request (the last message)."""
    return {r.name: r.response for r in request.messages[-1].tool_results}


def test_tool_then_answer():
    llm = ScriptedLLM([tool_call("get_solution"), tool_call(FINAL_ANSWER, answer="3 moves.")])
    trace = Trace("r1", "test", "How many moves?")
    assert run_agent(llm, task(), trace) == {"answer": "3 moves."}

    first = llm.requests[0]
    assert first.require_tool_call is True
    assert [t.name for t in first.tools] == ["get_solution", "explain_move", "broken", FINAL_ANSWER]  # no "secret"
    assert tool_results(llm.requests[1]) == {"get_solution": {"moves": "R U F", "move_count": 3}}
    assert [(s["kind"], s["name"]) for s in trace.steps] == [
        ("model", "scripted"), ("tool", "get_solution"), ("model", "scripted"), ("answer", FINAL_ANSWER),
    ]
    assert trace.request_count == 2 and trace.input_tokens == 200


def test_several_tools_in_one_turn_keep_their_order_and_ids():
    llm = ScriptedLLM(
        [tool_calls(("explain_move", {"step": 1}), ("explain_move", {"step": 3})), tool_call(FINAL_ANSWER, answer="R then F")]
    )
    run_agent(llm, task())
    results = llm.requests[1].messages[-1].tool_results
    assert [(r.response["notation"], r.id) for r in results] == [("R", "call-0"), ("F", "call-1")]


def test_problems_go_back_to_the_model_instead_of_crashing():
    llm = ScriptedLLM(
        [
            tool_calls(("explain_move", {"step": 9}), ("secret", {}), ("broken", {}), ("nope", {})),
            tool_call(FINAL_ANSWER, answer="Sorry."),
        ]
    )
    run_agent(llm, task())
    results = [r.response["error"] for r in llm.requests[1].messages[-1].tool_results]
    assert results[0].startswith("Invalid arguments: $.step: must be at most 3")
    assert results[1] == "Tool 'secret' is not available here."  # not on the allowlist
    assert results[2].startswith("The tool failed:")
    assert results[3] == "Tool 'nope' is not available here."


def test_an_invalid_answer_is_sent_back_and_can_be_fixed():
    llm = ScriptedLLM([tool_call(FINAL_ANSWER, answer=""), tool_call(FINAL_ANSWER, answer="Fixed.")])
    assert run_agent(llm, task()) == {"answer": "Fixed."}
    error = tool_results(llm.requests[1])[FINAL_ANSWER]["error"]
    assert error.startswith("Answer rejected: $.answer: must have at least 1 characters")


def test_the_answer_must_come_after_reading_tool_results():
    llm = ScriptedLLM(
        [tool_calls(("get_solution", {}), (FINAL_ANSWER, {"answer": "Guess"})), tool_call(FINAL_ANSWER, answer="3 moves.")]
    )
    assert run_agent(llm, task()) == {"answer": "3 moves."}
    results = tool_results(llm.requests[1])
    assert results["get_solution"]["move_count"] == 3
    assert "on its own" in results[FINAL_ANSWER]["error"]


def test_plain_text_gets_a_nudge():
    llm = ScriptedLLM([text_reply("3 moves"), tool_call(FINAL_ANSWER, answer="3 moves.")])
    assert run_agent(llm, task()) == {"answer": "3 moves."}
    assert "call final_answer" in llm.requests[1].messages[-1].text


def test_step_limit():
    llm = ScriptedLLM([tool_call("get_solution")] * 4)
    with pytest.raises(AgentStopped) as stopped:
        run_agent(llm, task(max_steps=4))
    assert stopped.value.reason == "step_limit" and len(llm.requests) == 4


def test_time_limit():
    now = [0.0]  # a fake clock, in seconds

    def slow_tool(args):
        now[0] += 50  # this tool "takes" 50 seconds
        return {"ok": True}

    slow = ToolRegistry([Tool("get_solution", "Slow.", NO_ARGS, slow_tool)])
    llm = ScriptedLLM([tool_call("get_solution"), tool_call("get_solution")])
    with pytest.raises(AgentStopped) as stopped:
        run_agent(llm, task(tools=slow, allowed_tools=["get_solution"], deadline_seconds=45), clock=lambda: now[0])
    assert stopped.value.reason == "time_limit"
    assert len(llm.requests) == 1  # no new request after the deadline


def test_model_errors_reach_the_caller():
    with pytest.raises(LLMRateLimited):
        run_agent(ScriptedLLM([LLMRateLimited("quota")]), task())


def test_progress_is_reported_per_tool_call():
    seen = []
    llm = ScriptedLLM([tool_call("get_solution"), tool_call(FINAL_ANSWER, answer="3 moves.")])
    run_agent(llm, task(), on_progress=lambda step, tool: seen.append((step, tool)))
    assert seen == [(1, "get_solution")]
