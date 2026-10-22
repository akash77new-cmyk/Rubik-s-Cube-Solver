"""The Gemini client: the exact request it sends and how it reads answers and errors.

A fake transport stands in for the network, so no test calls Google. The last tests
use a real local HTTP server, to cover the urllib code too.
"""

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.ai.gemini import GeminiClient
from backend.ai.llm import (
    LLMAuthError,
    LLMBadRequest,
    LLMBadResponse,
    LLMRateLimited,
    LLMRequest,
    LLMUnavailable,
    Message,
    ToolResult,
    ToolSpec,
)

STEP = {
    "type": "object",
    "properties": {"step": {"type": "integer", "minimum": 1}},
    "required": ["step"],
    "additionalProperties": False,
}
TOOLS = [
    ToolSpec("get_solution", "The solution.", {"type": "object", "properties": {}, "additionalProperties": False}),
    ToolSpec("explain_move", "One move.", STEP),
]

#: An answer in the shape Gemini 3 sends: a function call with a thought signature.
CALL_ANSWER = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {"functionCall": {"id": "c1", "name": "explain_move", "args": {"step": 2}}, "thoughtSignature": "SIG"}
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 15, "thoughtsTokenCount": 30},
    "modelVersion": "gemini-test-001",
}


class FakeTransport:
    """Records each request and plays back (status, body) answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, payload = answer
        return status, json.dumps(payload).encode("utf-8")


def client(transport, **kwargs):
    return GeminiClient("KEY-123", "gemini-test", transport=transport, sleep=lambda s: None, **kwargs)


def ask(gemini, messages=None):
    return gemini.generate(
        LLMRequest(system="Be brief.", messages=messages or [Message.user("Step 2?")], tools=TOOLS, require_tool_call=True)
    )


def test_the_request_body_and_headers():
    transport = FakeTransport((200, CALL_ANSWER))
    ask(client(transport, thinking_level="low"))
    call = transport.calls[0]
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert call["headers"]["x-goog-api-key"] == "KEY-123" and "KEY-123" not in call["url"]
    body = call["body"]
    assert body["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Step 2?"}]}]
    declarations = body["tools"][0]["functionDeclarations"]
    assert declarations[0] == {"name": "get_solution", "description": "The solution."}  # no empty schema
    assert declarations[1]["parameters"] == {
        "type": "object",
        "properties": {"step": {"type": "integer", "minimum": 1}},
        "required": ["step"],
    }  # additionalProperties is checked in code but not sent: Gemini rejects it
    assert body["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}
    assert body["generationConfig"] == {"maxOutputTokens": 8192, "thinkingConfig": {"thinkingLevel": "low"}}


def test_no_thinking_config_unless_set():
    transport = FakeTransport((200, CALL_ANSWER))
    ask(client(transport))
    assert "thinkingConfig" not in transport.calls[0]["body"]["generationConfig"]


def test_reading_a_function_call():
    response = ask(client(FakeTransport((200, CALL_ANSWER))))
    (call,) = response.tool_calls
    assert (call.name, call.args, call.id) == ("explain_move", {"step": 2}, "c1")
    assert response.usage.input_tokens == 120 and response.usage.thinking_tokens == 30
    assert response.model == "gemini-test-001"


def test_the_model_turn_and_tool_results_are_sent_back_correctly():
    """Gemini 3 rejects a follow-up request that drops the thought signature."""
    transport = FakeTransport((200, CALL_ANSWER), (200, CALL_ANSWER))
    gemini = client(transport)
    first = ask(gemini)
    results = Message.results([ToolResult("explain_move", {"notation": "U'"}, "c1")])
    ask(gemini, [Message.user("Step 2?"), first.message, results])
    contents = transport.calls[1]["body"]["contents"]
    assert contents[1] == CALL_ANSWER["candidates"][0]["content"]  # unchanged, signature included
    assert contents[2] == {
        "role": "user",
        "parts": [{"functionResponse": {"name": "explain_move", "response": {"notation": "U'"}, "id": "c1"}}],
    }


def test_text_answers_and_thought_summaries():
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "Hello"}]}, "finishReason": "STOP"}
        ]
    }
    response = ask(client(FakeTransport((200, payload))))
    assert response.text == "Hello" and response.tool_calls == []
    assert response.message.raw["role"] == "model"


@pytest.mark.parametrize(
    "status, error_type, words",
    [
        (429, LLMRateLimited, "quota"),
        (403, LLMAuthError, "API key"),
        (404, LLMBadRequest, "HTTP 404"),
        (400, LLMBadRequest, "HTTP 400"),
    ],
)
def test_errors_become_typed_exceptions(status, error_type, words):
    body = {"error": {"code": status, "message": "Details from Google.", "status": "X"}}
    with pytest.raises(error_type, match=words) as error:
        ask(client(FakeTransport((status, body))))
    assert "Details from Google." in str(error.value)


def test_a_bad_key_is_an_auth_error_even_with_http_400():
    body = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}
    with pytest.raises(LLMAuthError, match="rejected the API key"):
        ask(client(FakeTransport((400, body))))


def test_overloaded_is_retried_once():
    transport = FakeTransport((503, {"error": {"message": "overloaded"}}), (200, CALL_ANSWER))
    assert ask(client(transport)).tool_calls[0].name == "explain_move"
    assert len(transport.calls) == 2


def test_a_network_error_twice_gives_up():
    transport = FakeTransport(OSError("connection reset"), TimeoutError("timed out"))
    with pytest.raises(LLMUnavailable, match="timed out"):
        ask(client(transport))
    assert len(transport.calls) == 2  # one try + one retry


def test_an_answer_cut_off_midway_is_retried():
    transport = FakeTransport(http.client.IncompleteRead(b'{"candidates"'), (200, CALL_ANSWER))
    assert ask(client(transport)).tool_calls[0].name == "explain_move"
    assert len(transport.calls) == 2


def test_a_blocked_or_empty_answer_is_an_error():
    with pytest.raises(LLMBadResponse, match="blocked: SAFETY"):
        ask(client(FakeTransport((200, {"promptFeedback": {"blockReason": "SAFETY"}}))))
    empty = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
    with pytest.raises(LLMBadResponse, match="MAX_TOKENS"):
        ask(client(FakeTransport((200, empty))))


def test_a_key_is_required():
    with pytest.raises(ValueError):
        GeminiClient("", "gemini-test")


# --- A real HTTP round trip (local server, no internet) --------------------------------
class _Handler(BaseHTTPRequestHandler):
    answers: list = []
    seen: list = []

    def do_POST(self):  # noqa: N802 - the http.server API
        length = int(self.headers["Content-Length"])
        type(self).seen.append((self.path, self.headers["x-goog-api-key"], json.loads(self.rfile.read(length))))
        status, payload = type(self).answers.pop(0)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep test output quiet
        pass


@pytest.fixture
def local_gemini():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    _Handler.answers, _Handler.seen = [], []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1beta", _Handler
    server.shutdown()
    server.server_close()


def test_real_http_success_and_rate_limit(local_gemini):
    base_url, handler = local_gemini
    handler.answers = [(200, CALL_ANSWER), (429, {"error": {"message": "Quota exceeded"}})]
    gemini = GeminiClient("KEY-123", "gemini-test", base_url=base_url, timeout=5)
    assert ask(gemini).tool_calls[0].args == {"step": 2}
    with pytest.raises(LLMRateLimited, match="Quota exceeded"):
        ask(gemini)
    path, key, body = handler.seen[0]
    assert path == "/v1beta/models/gemini-test:generateContent" and key == "KEY-123"
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"


def test_real_http_nobody_listening_is_unavailable():
    gemini = GeminiClient("KEY-123", "gemini-test", base_url="http://127.0.0.1:9/v1beta", timeout=2, retries=0)
    with pytest.raises(LLMUnavailable, match="Could not reach Gemini"):
        ask(gemini)
