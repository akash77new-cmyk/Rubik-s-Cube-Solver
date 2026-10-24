"""Provider-neutral types for talking to a language model (LLM).

The agent loop only uses these types, so it works the same with Gemini
(``gemini.py``) and with the scripted fake used in tests (``fake.py``). Supporting
another provider means writing one more client class; nothing else changes.

A conversation is a list of ``Message`` objects. A model turn can contain text
and/or tool calls ("please run get_solution"). The app answers tool calls with a
message of tool results, and the model takes its next turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool the model may call: its name, what it does, and its arguments (JSON Schema)."""

    name: str
    description: str
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """The model asks the app to run a tool. ``id`` pairs the call with its result."""

    name: str
    args: Dict[str, Any]
    id: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    """What the app sends back for one tool call (always a JSON object)."""

    name: str
    response: Dict[str, Any]
    id: Optional[str] = None


@dataclass
class Message:
    """One turn of the conversation."""

    role: str  # "user" (the app or the user) or "model"
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    #: PNG images sent with a user message, after its text (Phase 11: sticker crops for the
    #: vision check). Only small crops are ever sent, never a camera frame.
    images: List[bytes] = field(default_factory=list)
    #: The provider's own copy of a model turn, sent back unchanged in the next
    #: request. Gemini 3 hides a "thought signature" in it, and rejects a request
    #: that changes or drops it.
    raw: Optional[Dict[str, Any]] = None

    @classmethod
    def user(cls, text: str, images: Optional[List[bytes]] = None) -> "Message":
        return cls(role="user", text=text, images=list(images or []))

    @classmethod
    def results(cls, results: List[ToolResult]) -> "Message":
        return cls(role="user", tool_results=list(results))


@dataclass(frozen=True)
class Usage:
    """Tokens used by one request (what the provider bills and rate-limits)."""

    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0


@dataclass
class LLMRequest:
    system: str
    messages: List[Message]
    tools: List[ToolSpec] = field(default_factory=list)
    #: True = the model must answer with a tool call, never with plain text.
    require_tool_call: bool = False
    #: A safety cap, not a target. Gemini counts its thinking tokens in it, so a small
    #: cap can cut an answer off while the model is still thinking.
    max_output_tokens: int = 8192


@dataclass
class LLMResponse:
    message: Message
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    model: str = ""

    @property
    def tool_calls(self) -> List[ToolCall]:
        return self.message.tool_calls

    @property
    def text(self) -> str:
        return self.message.text


# --------------------------------------------------------------------------------------
# Errors. Each has a short ``reason`` code, used in traces and for the fallback message.
# --------------------------------------------------------------------------------------


class LLMError(Exception):
    """A model request failed."""

    reason = "error"


class LLMRateLimited(LLMError):
    """Too many requests: the provider's limit (HTTP 429) or the app's own budget."""

    reason = "rate_limited"


class LLMBudgetExceeded(LLMRateLimited):
    """The app's own request budget is used up (see budget.py); Google was not asked."""

    reason = "budget"


class LLMAuthError(LLMError):
    """The API key was rejected (HTTP 401/403)."""

    reason = "auth"


class LLMBadRequest(LLMError):
    """The provider refused the request (HTTP 400/404), e.g. an unknown model name."""

    reason = "bad_request"


class LLMUnavailable(LLMError):
    """The provider could not be reached or is overloaded (network error, timeout, 5xx)."""

    reason = "unavailable"


class LLMBadResponse(LLMError):
    """The provider answered, but with nothing usable (blocked or empty)."""

    reason = "bad_response"


class LLMClient(Protocol):
    """What the agent needs from a model provider."""

    provider: str  # e.g. "gemini"
    model: str  # e.g. "gemini-3.5-flash-lite"

    def generate(self, request: LLMRequest) -> LLMResponse:
        """One request to the model. Raises an ``LLMError`` subclass on failure."""
        ...


class Embedder(Protocol):
    """What the RAG coach needs from an embedding model (Phase 7)."""

    model: str  # e.g. "gemini-embedding-001"

    def embed(self, texts: List[str], task: str) -> List[List[float]]:
        """One vector per text. Raises an ``LLMError`` subclass on failure."""
        ...
