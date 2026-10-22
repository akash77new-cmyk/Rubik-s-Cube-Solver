"""Tools: functions the model may ask the app to run.

The model never touches the app directly. It can only *ask* for a registered tool
by name; the registry checks that the tool is allowed for this task and that the
arguments match the tool's schema, runs it, and returns its result as JSON.

Rules for tools (see CLAUDE.md section 4):
- A tool computes facts in code; the model only reads them.
- Tools never change the user's cube. A tool may *propose* a change (Phase 5);
  applying it is always a separate action the user confirms.
- A tool returns a JSON object. Problems come back as ``{"error": "..."}``, so the
  model can read what went wrong and try again; they never crash the app.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List

from backend.ai.llm import ToolSpec
from backend.ai.schema import check_schema, validate

log = logging.getLogger(__name__)

#: Gemini's rule for function names.
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: The schema of a tool that takes no arguments.
NO_ARGS: Dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # the model reads this to decide when to call the tool
    parameters: Dict[str, Any]  # JSON Schema of the arguments (an object)
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters)


class ToolRegistry:
    """All the tools one feature offers, by name."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: Dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> Tool:
        if not _NAME.match(tool.name):
            raise ValueError(f"Invalid tool name {tool.name!r}")
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        if tool.parameters.get("type") != "object":
            raise ValueError(f"Tool {tool.name!r}: parameters must be an object schema")
        check_schema(tool.parameters)  # an unsupported keyword fails now, not mid-conversation
        self._tools[tool.name] = tool
        return tool

    def names(self) -> List[str]:
        return list(self._tools)

    def specs(self, names: Iterable[str]) -> List[ToolSpec]:
        """Declarations for the model, for these tools only (KeyError if one is unknown)."""
        return [self._tools[name].spec() for name in names]

    def call(self, name: str, args: Dict[str, Any], allowed: Iterable[str]) -> Dict[str, Any]:
        """Run one tool call from the model. Never raises: problems become {"error": ...}."""
        if name not in set(allowed):
            return {"error": f"Tool '{name}' is not available here."}
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"There is no tool called '{name}'."}
        errors = validate(args, tool.parameters)
        if errors:
            return {"error": "Invalid arguments: " + "; ".join(errors[:5])}
        try:
            result = tool.handler(dict(args))
        except Exception as exc:  # a bug in a tool must not crash the agent
            log.exception("Tool %s failed", name)
            return {"error": f"The tool failed: {exc}"}
        if not isinstance(result, dict):
            return {"error": "The tool returned no data."}
        return result
