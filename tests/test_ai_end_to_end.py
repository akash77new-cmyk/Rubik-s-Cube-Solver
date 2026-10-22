"""The whole AI path against tools/fake_gemini.py: real HTTP, thought signatures, tools, trace.

Both features: the Cube Assistant and the Smart Repair Agent.

No internet and no real key: the fake server runs on 127.0.0.1 inside the test.
"""

import threading
from http.server import HTTPServer

import pytest

from backend.ai.assistant import SnapshotContext
from backend.ai.repair_agent import RepairContext
from backend.ai.service import AIConfig, AIService
from backend.ai.tracing import TraceStore
from backend.db import connect
from tests.sessions import misread, new_session, readings_for, real_cube, with_solution
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


def test_a_repair_end_to_end(fake_gemini):
    ai = AIService.create(AIConfig(api_key=KEY, model="gemini-test", base_url=fake_gemini), None, lambda e, d: None)
    scan = misread(real_cube(), {("U", 1): "O"})
    proposal = ai.repair(RepairContext(scan, readings_for(scan, {("U", 1): ("O", "R", 0.51, 0.48)})))
    assert (proposal["source"], proposal["action"], proposal["requests"]) == ("gemini", "apply_fix", 2)
    assert [(c["face"], c["index"], c["to"]) for c in proposal["changes"]] == [("U", 1, "R")]


def test_the_coach_end_to_end_with_embeddings(fake_gemini):
    indexed = threading.Event()

    def publish(event, data):
        if event == "ai:status" and data["lessons"]["embedded"] == 37:
            indexed.set()

    config = AIConfig(api_key=KEY, model="gemini-test", base_url=fake_gemini, embed_model="gemini-embedding-001")
    ai = AIService.create(config, None, publish, database=connect("sqlite://"))
    ai.start_lessons()  # embeds all 37 lesson sections through the fake server
    assert indexed.wait(10)
    payload = ai.coach_answer("Which way do I turn B?")
    assert (payload["source"], payload["search"], payload["covered"]) == ("gemini", "vectors in Python", True)
    assert payload["citations"] == ["02-notation#the-tricky-sides-b-l-and-d"]


def test_the_fake_is_strict_about_thought_signatures():
    unsigned = {"role": "model", "parts": [{"functionCall": {"id": "id-x", "name": "get_solution", "args": {}}}]}
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Hi"}]}, unsigned],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
    }
    status, payload = answer(body)
    assert status == 400 and "thought_signature" in payload["error"]["message"]
