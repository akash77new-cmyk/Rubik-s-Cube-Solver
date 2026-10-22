"""The whole AI path against tools/fake_gemini.py: real HTTP, thought signatures, tools, trace.

No internet and no real key: the fake server runs on 127.0.0.1 inside the test.
"""

import threading
from http.server import HTTPServer

import pytest

from backend.ai.assistant import SnapshotContext
from backend.ai.service import AIConfig, AIService
from backend.ai.tracing import TraceStore
from backend.db import connect
from tests.sessions import new_session, with_solution
from tools.fake_gemini import KEY, Handler, answer


@pytest.fixture
def fake_gemini():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1beta"
    server.shutdown()
    server.server_close()


def ask(base_url, key, store=None):
    ai = AIService.create(AIConfig(api_key=key, model="gemini-test", base_url=base_url), store, lambda e, d: None)
    return ai.answer("How many moves?", SnapshotContext(with_solution(new_session()).snapshot))


def test_a_question_end_to_end(fake_gemini):
    store = TraceStore(connect("sqlite://"))
    payload = ask(fake_gemini, KEY, store)
    assert (payload["source"], payload["requests"], payload["toolCalls"]) == ("gemini", 2, 1)
    assert payload["answer"] == "Your solution has 3 moves: F' U' R'."
    (run,) = store.recent()
    assert [step["kind"] for step in run["steps"]] == ["model", "tool", "model", "answer"]
    assert run["steps"][0]["name"] == "gemini-fake-001"  # the model version the server reported


def test_a_wrong_key_falls_back(fake_gemini):
    payload = ask(fake_gemini, "wrong-key")
    assert payload["source"] == "fallback" and payload["reason"] == "Gemini rejected the API key"


def test_the_fake_is_strict_about_thought_signatures():
    unsigned = {"role": "model", "parts": [{"functionCall": {"id": "id-x", "name": "get_solution", "args": {}}}]}
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Hi"}]}, unsigned],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
    }
    status, payload = answer(body)
    assert status == 400 and "thought_signature" in payload["error"]["message"]
