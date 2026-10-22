"""The agent loop: let the model call tools until it gives a valid final answer.

    question ──► model ──► tool calls ──► app runs the tools ──► results ──► model ──► ...
                                                                       └──► final_answer ✓

How it stays safe (AI rule 6):
- **Allowlist:** the model is only told about the tools allowed for this task, and
  the registry refuses any other name.
- **Validated arguments:** every tool call is checked against the tool's schema.
- **Step limit and time limit:** at most ``max_steps`` model requests, and no new
  request after ``deadline_seconds``.
- **Structured answer:** the model answers by calling a special ``final_answer``
  tool whose arguments must match ``answer_schema`` (and pass ``answer_check``, if the
  task has one). A wrong answer is sent back with the reasons, and the model may fix
  it within the step limit.
- **Grounded answer:** ``final_answer`` must come alone, after the model has read
  the results of the tools it called. Calling it next to other tools is refused.
- **Traced:** every model request and tool call is recorded in the ``Trace``.

The model must call a tool on every turn (Gemini's mode "ANY"), so the loop never
has to guess whether plain text was meant as the answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from backend.ai.llm import LLMClient, LLMRequest, Message, ToolResult, ToolSpec
from backend.ai.schema import check_schema, validate
from backend.ai.tools import ToolRegistry
from backend.ai.tracing import Trace

FINAL_ANSWER = "final_answer"

#: Called after each tool call: (step number, tool name). The UI shows progress with it.
ProgressCallback = Callable[[int, str], None]


@dataclass
class AgentTask:
    system_prompt: str
    question: str
    tools: ToolRegistry
    allowed_tools: Sequence[str]
    answer_schema: Dict[str, Any]
    max_steps: int = 5
    deadline_seconds: float = 45.0
    #: Extra checks the schema can't express (e.g. "fix_id must be one the tool
    #: returned"). Returns problems as messages; [] = the answer is accepted.
    answer_check: Optional[Callable[[Dict[str, Any]], List[str]]] = None


class AgentStopped(Exception):
    """The agent ended without a valid answer."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason  # "step_limit" or "time_limit"


def run_agent(
    llm: LLMClient,
    task: AgentTask,
    trace: Optional[Trace] = None,
    on_progress: Optional[ProgressCallback] = None,
    clock: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Run the loop. Returns the validated answer.

    Raises ``AgentStopped`` (step or time limit) or an ``LLMError`` from the model;
    the caller turns both into the built-in fallback.
    """
    check_schema(task.answer_schema)
    final = ToolSpec(
        FINAL_ANSWER,
        "Give your final answer to the user. Call it on its own, after reading the "
        "results of the other tools.",
        task.answer_schema,
    )
    tools = task.tools.specs(task.allowed_tools) + [final]
    messages: List[Message] = [Message.user(task.question)]
    started = clock()

    for step in range(1, task.max_steps + 1):
        if clock() - started > task.deadline_seconds:
            raise AgentStopped("time_limit", f"No answer within {task.deadline_seconds:.0f} s")

        request_started = clock()
        response = llm.generate(
            LLMRequest(system=task.system_prompt, messages=list(messages), tools=tools, require_tool_call=True)
        )
        if trace is not None:
            trace.model_step(response, (clock() - request_started) * 1000)
        messages.append(response.message)

        if not response.tool_calls:  # shouldn't happen in mode ANY, but never trust it
            messages.append(Message.user("Reply by calling a tool. To answer, call final_answer."))
            continue

        others = [call for call in response.tool_calls if call.name != FINAL_ANSWER]
        results: List[ToolResult] = []
        for call in response.tool_calls:
            call_started = clock()
            if call.name == FINAL_ANSWER:
                if others:
                    result: Dict[str, Any] = {
                        "error": "Call final_answer on its own, after you have read the tool results."
                    }
                else:
                    errors = validate(call.args, task.answer_schema)
                    if not errors and task.answer_check is not None:
                        errors = task.answer_check(dict(call.args))
                    if not errors:
                        answer = dict(call.args)
                        if trace is not None:
                            trace.answer_step(answer)
                        return answer
                    result = {"error": "Answer rejected: " + "; ".join(errors[:5]) + ". Call final_answer again."}
            else:
                result = task.tools.call(call.name, call.args, task.allowed_tools)
            if trace is not None:
                trace.tool_step(call, result, (clock() - call_started) * 1000)
            if on_progress is not None:
                on_progress(step, call.name)
            results.append(ToolResult(call.name, result, call.id))
        messages.append(Message.results(results))

    raise AgentStopped("step_limit", f"No valid answer after {task.max_steps} model requests")
