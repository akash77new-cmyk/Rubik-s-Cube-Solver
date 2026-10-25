"""The engine's side of Phase 9: commands run in the sender's session; accounts next to the database."""

import time

import pytest

from backend.db import connect
from backend.engine import VisionEngine
from backend.services.sessions import Visitor


class FakeClient:
    """Stands in for the web server's connection: records what the engine sends back."""

    def __init__(self):
        self.messages = []

    def send_json(self, message):
        self.messages.append(message)
        return True

    def ack(self, request_id, timeout=10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.messages:
                if message["event"] == "ack" and message["data"]["requestId"] == request_id:
                    return message["data"]["result"]
            time.sleep(0.02)
        raise AssertionError(f"no answer to {request_id}")


@pytest.fixture
def engine():
    engine = VisionEngine(connect("sqlite://"), port=0)  # never started: no socket is opened
    yield engine
    engine.sessions.shutdown()


GUEST_A, GUEST_B = "g:aaaaaaaaaaaaaaaa", "g:bbbbbbbbbbbbbbbb"


def test_each_command_runs_in_its_senders_session(engine):
    client = FakeClient()
    engine._on_command({"command": "cube.scramble", "payload": {"length": 10}, "session": GUEST_A}, client)
    engine._on_command({"command": "cube.reset", "payload": {}, "session": GUEST_B}, client)
    engine._on_command({"command": "touch", "payload": {}, "session": "g:cccccccccccccccc"}, client)
    a, b = engine.sessions.get(Visitor(GUEST_A)), engine.sessions.get(Visitor(GUEST_B))
    assert a.snapshot()["cubeSource"] == "scramble" and b.snapshot()["cubeSource"] != "scramble"
    assert sorted(engine.sessions.keys()) == [GUEST_A, GUEST_B]


def test_a_new_web_server_gets_what_everyone_shares_but_no_ones_state(engine):
    client = FakeClient()
    engine._on_connect(client)
    assert [m["event"] for m in client.messages] == ["logs", "solver", "camera:owner"]


def test_sign_up_log_in_and_delete_through_the_engine(engine):
    client = FakeClient()

    def ask(command, payload, request_id):
        engine._on_command({"command": command, "payload": payload, "requestId": request_id}, client)
        return client.ack(request_id)

    created = ask("auth.signup", {"email": "akash@example.com", "password": "cube-solver-123"}, "r1")
    assert created == {"ok": True, "user": {"id": 1, "email": "akash@example.com"}}
    assert ask("auth.signup", {"email": "akash@example.com", "password": "cube-solver-123"}, "r2")["ok"] is False
    assert ask("auth.login", {"email": "akash@example.com", "password": "wrong-one"}, "r3") == {
        "ok": False, "error": "Wrong email or password."}
    assert ask("auth.login", {"email": "akash@example.com", "password": "cube-solver-123"}, "r4")["ok"] is True

    engine._on_command({"command": "cube.scramble", "payload": {}, "session": "u:1",
                        "user": {"id": 1, "email": "akash@example.com"}}, client)
    assert "u:1" in engine.sessions.keys()
    assert ask("auth.delete", {"user_id": 1, "password": "wrong-one"}, "r5")["ok"] is False
    assert ask("auth.delete", {"user_id": 1, "password": "cube-solver-123"}, "r6") == {"ok": True}
    assert "u:1" not in engine.sessions.keys()  # the account's session was closed too
