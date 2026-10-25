"""Login tokens (JWT) and the login limiter (Phase 9)."""

import base64
import json

import jwt

from backend.server.auth import (
    GUEST_TOKEN_SECONDS,
    USER_TOKEN_SECONDS,
    LoginLimiter,
    issue_token,
    new_guest,
    public_view,
    read_token,
    session_key,
)

SECRET = "test-secret"
USER = {"kind": "user", "id": 12, "email": "akash@example.com"}


def test_a_token_round_trips_and_says_who_it_is():
    assert read_token(SECRET, issue_token(SECRET, USER)) == USER
    guest = new_guest()
    assert read_token(SECRET, issue_token(SECRET, guest)) == guest
    assert session_key(USER) == "u:12" and session_key(guest) == f"g:{guest['id']}"
    assert public_view(guest) == {"kind": "guest"}  # a guest's id stays private


def test_tokens_expire():
    claims = jwt.decode(issue_token(SECRET, USER, now=1000), options={"verify_signature": False})
    assert claims["exp"] - claims["iat"] == USER_TOKEN_SECONDS
    assert read_token(SECRET, issue_token(SECRET, USER, now=1000)) is None  # issued long ago: expired
    guest_claims = jwt.decode(issue_token(SECRET, new_guest()), options={"verify_signature": False})
    assert guest_claims["exp"] - guest_claims["iat"] == GUEST_TOKEN_SECONDS


def test_a_changed_or_forged_token_is_refused():
    token = issue_token(SECRET, USER)
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    claims["sub"] = "1"  # try to become account 1
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    assert read_token(SECRET, f"{header}.{forged}.{signature}") is None  # the signature no longer matches
    assert read_token("another-secret", token) is None
    unsigned = jwt.encode({"sub": "1", "kind": "user", "email": "x@y.z", "iat": 1, "exp": 4102444800,
                           "iss": "cube-solver"}, key=None, algorithm="none")
    assert read_token(SECRET, unsigned) is None  # "alg": "none" is never accepted
    assert read_token(SECRET, "not-a-token") is None and read_token(SECRET, None) is None


def test_the_limiter_blocks_an_email_after_five_wrong_passwords():
    now = [0.0]
    limiter = LoginLimiter(clock=lambda: now[0])
    for _ in range(4):
        limiter.failed("akash@example.com")
    assert limiter.wait_seconds("akash@example.com") == 0
    limiter.failed("akash@example.com")
    assert limiter.wait_seconds("akash@example.com") > 800  # about 15 minutes
    assert limiter.wait_seconds("someone@example.com") == 0  # other accounts are not affected
    now[0] = LoginLimiter.WINDOW_SECONDS + 1
    assert limiter.wait_seconds("akash@example.com") == 0  # old failures expire
    limiter.failed("akash@example.com")
    limiter.succeeded("akash@example.com")
    assert limiter.wait_seconds("akash@example.com") == 0
