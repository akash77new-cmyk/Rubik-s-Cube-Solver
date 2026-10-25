"""The web server's side of accounts (Phase 9): endpoints, cookies, rooms, the camera stream.

The engine is replaced by a fake that records what the server sends it, so these tests
check exactly what crosses the process boundary: who each command says it comes from.
"""

import pytest

from backend.server.app import create_app
from backend.server.auth import COOKIE, LoginLimiter


class FakeEngine:
    """Answers auth.* requests like the engine would, and records every command."""

    def __init__(self):
        self.sent = []
        self.requests = []
        self.users = {}
        self.down = False

    def send(self, command, payload=None, session=None, user=None, request_id=None):
        self.sent.append((command, payload, session, user))
        return True

    def request(self, command, payload=None, timeout=15.0):
        self.requests.append((command, payload))
        if self.down:
            return None
        if command == "auth.signup":
            if payload["email"] in self.users:
                return {"ok": False, "error": "An account with this email already exists. Log in instead."}
            self.users[payload["email"]] = (len(self.users) + 1, payload["password"])
            return {"ok": True, "user": {"id": self.users[payload["email"]][0], "email": payload["email"]}}
        if command == "auth.login":
            found = self.users.get(payload["email"])
            if found is None or found[1] != payload["password"]:
                return {"ok": False, "error": "Wrong email or password."}
            return {"ok": True, "user": {"id": found[0], "email": payload["email"]}}
        if command == "auth.delete":
            return {"ok": payload["password"] == "cube-solver-123"}
        return {"ok": False}


@pytest.fixture
def server(monkeypatch):
    app, socketio, engine = create_app()
    fake = FakeEngine()
    monkeypatch.setattr(engine, "send", fake.send)
    monkeypatch.setattr(engine, "request", fake.request)
    relay = engine._routed_handlers[0]
    return app, socketio, fake, relay


def cookie(response):
    (header,) = [value for value in response.headers.getlist("Set-Cookie") if value.startswith(COOKIE + "=")]
    return header


def test_a_new_browser_becomes_a_guest_with_an_httponly_cookie(server):
    app, _, _, _ = server
    client = app.test_client()
    first = client.get("/api/auth/me")
    assert first.get_json() == {"kind": "guest"}
    flags = cookie(first)
    assert "HttpOnly" in flags and "SameSite=Lax" in flags and "Path=/" in flags
    again = client.get("/api/auth/me")  # the cookie is sent back: the same guest, no new token
    assert again.get_json() == {"kind": "guest"} and not again.headers.getlist("Set-Cookie")


def test_sign_up_log_out_and_log_in(server):
    app, _, fake, _ = server
    client = app.test_client()
    created = client.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    assert created.status_code == 201 and created.get_json()["kind"] == "user"
    assert "Max-Age=604800" in cookie(created)  # a week
    assert client.get("/api/auth/me").get_json() == {"kind": "user", "id": 1, "email": "akash@example.com"}
    assert client.post("/api/auth/logout", json={}).get_json() == {"kind": "guest"}
    assert client.get("/api/auth/me").get_json() == {"kind": "guest"}
    login = client.post("/api/auth/login", json={"email": "AKASH@example.com ", "password": "cube-solver-123"})
    assert login.status_code == 200 and login.get_json()["email"] == "akash@example.com"
    assert fake.requests[-1] == ("auth.login", {"email": "akash@example.com", "password": "cube-solver-123"})


def test_bad_requests_get_clear_answers(server):
    app, _, fake, _ = server
    client = app.test_client()
    assert client.post("/api/auth/login", data="email=a&password=b").status_code == 415  # JSON only (CSRF)
    client.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    duplicate = client.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    assert duplicate.status_code == 400 and "already exists" in duplicate.get_json()["error"]
    fake.down = True
    assert client.post("/api/auth/login", json={"email": "a@b.co", "password": "x"}).status_code == 503


def test_five_wrong_passwords_lock_that_email(server):
    app, _, _, _ = server
    client = app.test_client()
    for _ in range(LoginLimiter.MAX_FAILURES):
        assert client.post("/api/auth/login", json={"email": "a@b.co", "password": "nope"}).status_code == 401
    locked = client.post("/api/auth/login", json={"email": "a@b.co", "password": "nope"})
    assert locked.status_code == 429 and int(locked.headers["Retry-After"]) > 0


def test_deleting_needs_a_logged_in_user_and_takes_the_id_from_the_token(server):
    app, _, fake, _ = server
    client = app.test_client()
    client.get("/api/auth/me")
    assert client.post("/api/auth/delete", json={"password": "x"}).status_code == 401  # a guest
    client.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    assert client.post("/api/auth/delete", json={"password": "wrong", "user_id": 7}).status_code == 403
    assert fake.requests[-1] == ("auth.delete", {"user_id": 1, "password": "wrong"})  # never the body's id
    assert client.post("/api/auth/delete", json={"password": "cube-solver-123"}).get_json() == {"kind": "guest"}


def test_each_socket_is_tagged_with_its_visitor_and_gets_only_its_events(server):
    app, socketio, fake, relay = server
    guest_http, user_http = app.test_client(), app.test_client()
    guest_http.get("/api/auth/me")
    user_http.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    guest = socketio.test_client(app, flask_test_client=guest_http)
    user = socketio.test_client(app, flask_test_client=user_http)
    tool = socketio.test_client(app)  # no cookie at all, like verify.py
    syncs = [(session, user_info) for command, _, session, user_info in fake.sent if command == "sync"]
    assert syncs[1] == ("u:1", {"id": 1, "email": "akash@example.com"})
    assert syncs[0][0].startswith("g:") and syncs[2][0].startswith("s:")

    user.emit("command", {"command": "cube.scramble", "payload": {"length": 5}})
    assert fake.sent[-1] == ("cube.scramble", {"length": 5}, "u:1", {"id": 1, "email": "akash@example.com"})
    assert user.emit("command", {"command": "auth.delete", "payload": {}}, callback=True)["ok"] is False

    for client in (guest, user, tool):
        client.get_received()
    relay("state", {"mode": "scan"}, "u:1")  # an event for the account's session...
    relay("log", {"message": "hi"}, None)  # ...and one for everyone
    assert [m["name"] for m in user.get_received()] == ["state", "log"]
    assert [m["name"] for m in guest.get_received()] == ["log"]
    assert [m["name"] for m in tool.get_received()] == ["log"]


def test_only_the_camera_users_browser_may_watch_it(server):
    app, _, _, relay = server
    owner, other = app.test_client(), app.test_client()
    owner.post("/api/auth/signup", json={"email": "akash@example.com", "password": "cube-solver-123"})
    other.get("/api/auth/me")
    relay("camera:owner", {"session": "u:1"}, None)
    assert other.get("/api/stream.mjpg").status_code == 403
    assert other.get("/api/snapshot.jpg").status_code == 403
    assert owner.get("/api/snapshot.jpg").status_code == 503  # allowed; just no frame in this test
    relay("camera:owner", {"session": None}, None)
    assert other.get("/api/snapshot.jpg").status_code == 503


def test_the_rest_endpoint_refuses_internal_commands(server):
    app, _, fake, _ = server
    client = app.test_client()
    assert client.post("/api/command", json={"command": "auth.signup", "payload": {}}).status_code == 400
    assert client.post("/api/command", json={"command": "touch"}).status_code == 400
    client.post("/api/command", json={"command": "cube.reset"})
    assert fake.sent[-1][2] == "local"  # no token: the "local" session
