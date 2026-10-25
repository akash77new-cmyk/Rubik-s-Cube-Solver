"""Tokens and login protection for the web server (Phase 9).

**JWT (JSON Web Token).** After a sign-up or login the server gives the browser a small
signed document saying who it is::

    header.payload.signature        payload = {"sub": "12", "email": "a@b.co", "kind": "user",
                                               "iat": issued, "exp": expires, "iss": "cube-solver"}

The signature is an HMAC-SHA256 of the header and payload with a key derived from
``FLASK_SECRET_KEY`` (SHA-256 of it, so the key is always 32 bytes and separate from the
key Flask itself uses). Anyone
can *read* a JWT, but nobody without the key can *change* one: a changed payload no longer
matches its signature. So the server checks a request's identity without a database
lookup ("stateless"). Decoding pins the algorithm to HS256, so a token that says
``"alg": "none"`` is refused.

**Where the token lives: an HttpOnly cookie** (``cube_token``), not localStorage:

- ``HttpOnly``: JavaScript can't read it, so an injected script (XSS) can't steal it.
- ``SameSite=Lax``: the browser doesn't send it with another site's POST, which blocks
  cross-site request forgery (CSRF). The auth endpoints also accept only JSON bodies, which
  a plain HTML form on another site can't send.
- ``Secure`` in production: only sent over HTTPS.
- It's sent automatically with Socket.IO's handshake and the camera stream, which can't
  carry an Authorization header.

**Guests** get a token too (``"kind": "guest"`` with a random id), so every browser has its
own session without signing up.

**Login limiter.** At most ``MAX_FAILURES`` wrong passwords per email in ``WINDOW_SECONDS``;
then that email must wait. It slows down password guessing against one account.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

import jwt

COOKIE = "cube_token"
ALGORITHM = "HS256"
ISSUER = "cube-solver"
USER_TOKEN_SECONDS = 7 * 24 * 3600  # log in again after a week
GUEST_TOKEN_SECONDS = 30 * 24 * 3600

Identity = Dict[str, Any]  # {"kind": "user", "id": 12, "email": ...} or {"kind": "guest", "id": "9f2c..."}


def signing_key(secret: str) -> bytes:
    """The token key: 32 bytes derived from the app's secret, used only for tokens."""
    return hashlib.sha256(b"cube-solver-jwt:" + secret.encode("utf-8")).digest()


def new_guest() -> Identity:
    return {"kind": "guest", "id": secrets.token_hex(8)}


def user_identity(user: Dict[str, Any]) -> Identity:
    return {"kind": "user", "id": int(user["id"]), "email": str(user["email"])}


def issue_token(secret: str, identity: Identity, now: Optional[float] = None) -> str:
    """A signed JWT for ``identity``."""
    issued = int(now if now is not None else time.time())
    lifetime = USER_TOKEN_SECONDS if identity["kind"] == "user" else GUEST_TOKEN_SECONDS
    claims: Dict[str, Any] = {
        "sub": str(identity["id"]),
        "kind": identity["kind"],
        "iat": issued,
        "exp": issued + lifetime,
        "iss": ISSUER,
    }
    if identity["kind"] == "user":
        claims["email"] = identity["email"]
    return jwt.encode(claims, signing_key(secret), algorithm=ALGORITHM)


def read_token(secret: str, token: Optional[str]) -> Optional[Identity]:
    """The identity in a valid token, or None (missing, expired, tampered, wrong key)."""
    if not token:
        return None
    try:
        claims = jwt.decode(
            token, signing_key(secret), algorithms=[ALGORITHM], issuer=ISSUER,
            options={"require": ["sub", "kind", "exp", "iat", "iss"]},
        )
    except jwt.InvalidTokenError:
        return None
    kind, subject = claims.get("kind"), str(claims.get("sub", ""))
    if kind == "user" and subject.isdigit() and claims.get("email"):
        return {"kind": "user", "id": int(subject), "email": str(claims["email"])}
    if kind == "guest" and len(subject) == 16 and all(c in "0123456789abcdef" for c in subject):
        return {"kind": "guest", "id": subject}
    return None


def session_key(identity: Identity) -> str:
    """The engine's session key for this identity: "u:12" or "g:9f2c..."."""
    return f"u:{identity['id']}" if identity["kind"] == "user" else f"g:{identity['id']}"


def public_view(identity: Identity) -> Dict[str, Any]:
    """What /api/auth/me tells the browser (a guest's id stays private)."""
    if identity["kind"] == "user":
        return {"kind": "user", "id": identity["id"], "email": identity["email"]}
    return {"kind": "guest"}


class LoginLimiter:
    """Counts wrong passwords per email, and blocks an email that had too many recently."""

    MAX_FAILURES = 5
    WINDOW_SECONDS = 15 * 60

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._failures: Dict[str, Deque[float]] = {}

    def _recent(self, key: str) -> Deque[float]:
        times = self._failures.setdefault(key, deque())
        cutoff = self._clock() - self.WINDOW_SECONDS
        while times and times[0] < cutoff:
            times.popleft()
        return times

    def wait_seconds(self, email: str) -> int:
        """0 if a login may be tried now, else how many seconds to wait."""
        with self._lock:
            times = self._recent(email)
            if not times:
                self._failures.pop(email, None)  # nothing to remember: keep the table small
            if len(times) < self.MAX_FAILURES:
                return 0
            return max(1, int(times[0] + self.WINDOW_SECONDS - self._clock()) + 1)

    def failed(self, email: str) -> None:
        with self._lock:
            self._recent(email).append(self._clock())

    def succeeded(self, email: str) -> None:
        with self._lock:
            self._failures.pop(email, None)
