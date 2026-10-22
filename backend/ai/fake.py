"""A scripted stand-in for a real model (AI rule 10: tests never call real APIs).

    llm = ScriptedLLM([
        tool_call("get_solution"),                              # 1st model turn
        tool_call("final_answer", answer="It has 20 moves."),   # 2nd model turn
    ])

Each ``generate()`` returns the next scripted turn and records the request, so a
test can check what the agent sent. A script entry can also be an exception
(it is raised) or a function of the request (its result is returned).
"""

from __future__ import annotations

from typing import Any, Callable, List, Sequence, Union

from backend.ai.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage

Step = Union[LLMResponse, Exception, Callable[[LLMRequest], LLMResponse]]


def tool_call(name: str, **args: Any) -> LLMResponse:
    """A model turn that calls one tool."""
    return tool_calls((name, args))


def tool_calls(*calls: Any) -> LLMResponse:
    """A model turn that calls several tools at once: tool_calls(("a", {}), ("b", {"x": 1}))."""
    parsed = [ToolCall(name, dict(args), id=f"call-{index}") for index, (name, args) in enumerate(calls)]
    return LLMResponse(
        message=Message(role="model", tool_calls=parsed),
        finish_reason="STOP",
        usage=Usage(input_tokens=100, output_tokens=10),
        model="scripted",
    )


def text_reply(text: str) -> LLMResponse:
    """A model turn with plain text and no tool call."""
    return LLMResponse(message=Message(role="model", text=text), finish_reason="STOP", model="scripted")


class ScriptedLLM:
    """An ``LLMClient`` that plays back a script."""

    provider = "scripted"
    model = "scripted"

    def __init__(self, script: Sequence[Step]) -> None:
        self._script: List[Step] = list(script)
        self.requests: List[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        # Keep a copy: the agent goes on adding to its message list after this call.
        self.requests.append(
            LLMRequest(
                system=request.system,
                messages=list(request.messages),
                tools=list(request.tools),
                require_tool_call=request.require_tool_call,
                max_output_tokens=request.max_output_tokens,
            )
        )
        if not self._script:
            raise AssertionError("ScriptedLLM: the script has no more turns")
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(request)
        return step
