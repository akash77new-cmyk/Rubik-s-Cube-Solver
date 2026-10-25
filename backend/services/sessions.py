"""Many visitors, one engine (Phase 9): a separate SolveSession for every visitor.

Before Phase 9 the engine had one SolveSession, so every visitor of the live site shared
one cube: one person's scramble changed everyone's screen. Now the web server tells the
engine *who* sent each command (a session key, from the visitor's token), and the
``SessionManager`` keeps one SolveSession per key:

==========  =======================  ==============================================
Key         Who                      What is kept
==========  =======================  ==============================================
``u:12``    the account with id 12   settings and solve history saved in the database;
                                     every tab and device of that account shares the session
``g:9f2c``  a guest (no account)     live site: everything lasts for the visit only;
                                     locally: saved as before Phase 9 (one person, one laptop)
``s:<sid>`` a client with no token   like a guest; tools such as ``verify.py --live``
``local``   commands with no sender  like a guest: old scripts and ``/api/command``
==========  =======================  ==============================================

What stays shared, on purpose: the solver, the lessons, the logs, saved colour profiles,
the AI request budget (it protects one API key) and the **camera**: one physical device,
so ``CameraGuard`` lets one session use it at a time.

Memory: a session costs about 0.25 MB. A session closes ``IDLE_SECONDS`` after its last
command, and the web server "touches" the sessions of visitors with an open tab every few
minutes, so a session ends only after its visitor has left. At most ``MAX_SESSIONS`` are
kept (the least recently used go first), so a flood of visitors can't fill Render's 512 MB.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend.services.analytics import AnalyticsStore
from backend.services.session import SolveSession
from backend.services.settings import AccountSettings, MemorySettings

LOCAL = "local"
#: The only session keys the engine accepts; anything else is treated as "local".
KEY_PATTERN = re.compile(r"^(u:\d{1,12}|g:[0-9a-f]{8,32}|s:[A-Za-z0-9_-]{1,40}|local)$")


@dataclass(frozen=True)
class Visitor:
    """Who a command comes from, as the web server's token check decided."""

    key: str
    email: Optional[str] = None

    @property
    def user_id(self) -> Optional[int]:
        return int(self.key[2:]) if self.key.startswith("u:") else None


def visitor_from(message: Dict[str, Any]) -> Visitor:
    """The visitor of one engine message: ``{"command", "payload", "session", "user"}``."""
    key = str(message.get("session") or LOCAL)
    if not KEY_PATTERN.match(key):
        key = LOCAL
    user = message.get("user") or {}
    email = user.get("email") if isinstance(user, dict) and key.startswith("u:") else None
    return Visitor(key, str(email) if email else None)


class CameraGuard:
    """One camera, many sessions: at most one session (its owner) may use it at a time."""

    def __init__(self, on_change: Callable[[Optional[str]], None] = lambda owner: None) -> None:
        self._lock = threading.Lock()
        self._owner: Optional[str] = None
        self._on_change = on_change  # the web server needs to know whose frames it streams

    @property
    def owner(self) -> Optional[str]:
        return self._owner

    def claim(self, key: str) -> bool:
        """True if ``key`` may use the camera now (it was free, or already theirs)."""
        with self._lock:
            if self._owner not in (None, key):
                return False
            changed = self._owner != key
            self._owner = key
        if changed:
            self._on_change(key)
        return True

    def release(self, key: str) -> None:
        with self._lock:
            if self._owner != key:
                return
            self._owner = None
        self._on_change(None)


@dataclass
class SharedServices:
    """Everything the engine creates once and every session uses."""

    settings: Any  # SettingsStore: the installation's settings
    profiles: Any  # ProfileStore
    solver: Any  # SolverEngine
    logs: Any  # LogBus
    accounts: Any  # AccountStore
    database: Any  # Database
    local_analytics: AnalyticsStore  # solves made without an account (used locally)
    publish: Callable[..., None]  # publish(event, data, to=key)
    publish_frame: Callable[[bytes], None]
    dataset: Any = None
    ai: Any = None
    classifier: Any = None
    color_model: Optional[Dict[str, Any]] = None
    production: bool = False


def build_session(visitor: Visitor, guard: CameraGuard, shared: SharedServices) -> SolveSession:
    """A new SolveSession for ``visitor``, with the stores their kind of visitor gets."""
    account = shared.accounts.get(visitor.user_id) if visitor.user_id is not None else None
    if account is not None:  # an account: its own settings and history, saved
        settings: Any = AccountSettings(shared.accounts, account.id, shared.settings.current)
        analytics = AnalyticsStore(shared.database, account.id)
    elif shared.production:  # a guest on the live site: nothing they do touches anyone else
        settings = MemorySettings(shared.settings.current)
        analytics = AnalyticsStore(None)
    else:  # locally: one person on a laptop, so everything is saved as before Phase 9
        settings = shared.settings
        analytics = shared.local_analytics
    key = visitor.key
    return SolveSession(
        settings=settings,
        profiles=shared.profiles,
        solver=shared.solver,
        logs=shared.logs,
        analytics=analytics,
        publish_event=lambda event, data: shared.publish(event, data, to=key),
        publish_frame=shared.publish_frame,
        dataset=shared.dataset,
        database=shared.database,
        ai=shared.ai,
        classifier=shared.classifier,
        color_model=shared.color_model,
        owner=key,
        camera_guard=guard,
        can_save_shared=account is not None or not shared.production,
        solver_events=False,
    )


class SessionManager:
    """Creates, finds and closes visitors' sessions."""

    #: A session nobody used for 30 minutes is closed (an account's saved data stays).
    IDLE_SECONDS = 30 * 60
    #: At most this many sessions at once (about 25 MB).
    MAX_SESSIONS = 100

    def __init__(
        self,
        factory: Callable[[Visitor, CameraGuard], SolveSession],
        on_camera_change: Callable[[Optional[str]], None] = lambda owner: None,
        clock: Callable[[], float] = time.monotonic,
        idle_seconds: float = IDLE_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self._factory = factory
        self.camera = CameraGuard(on_camera_change)
        self._clock = clock
        self.idle_seconds = idle_seconds
        self.max_sessions = max_sessions
        self._lock = threading.Lock()
        self._sessions: Dict[str, SolveSession] = {}
        self._last_used: Dict[str, float] = {}

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._sessions)

    def get(self, visitor: Visitor) -> SolveSession:
        """The visitor's session, created on their first command."""
        closed: List[SolveSession] = []
        with self._lock:
            session = self._sessions.get(visitor.key)
            if session is None:
                while len(self._sessions) >= self.max_sessions:
                    victim = self._least_recently_used()
                    if victim is None:
                        break
                    closed.append(self._remove(victim))
                session = self._factory(visitor, self.camera)
                self._sessions[visitor.key] = session
            self._last_used[visitor.key] = self._clock()
        for old in closed:
            old.shutdown()
        return session

    def touch(self, key: str) -> None:
        """The visitor still has a tab open: keep their session (never creates one)."""
        with self._lock:
            if key in self._sessions:
                self._last_used[key] = self._clock()

    def close(self, key: str) -> bool:
        with self._lock:
            session = self._remove(key) if key in self._sessions else None
        if session is None:
            return False
        session.shutdown()
        return True

    def prune(self) -> List[str]:
        """Close the sessions idle for longer than ``idle_seconds``. Returns their keys."""
        now = self._clock()
        with self._lock:
            idle = [
                key for key, used in self._last_used.items()
                if now - used > self.idle_seconds and key != self.camera.owner
            ]
            closed = [self._remove(key) for key in idle]
        for session in closed:
            session.shutdown()
        return idle

    def shutdown(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._last_used.clear()
        for session in sessions:
            session.shutdown()

    # ------------------------------------------------------------------
    def _least_recently_used(self) -> Optional[str]:
        """The session unused for longest, never the one using the camera (caller holds the lock)."""
        candidates = [key for key in self._last_used if key != self.camera.owner]
        return min(candidates, key=self._last_used.__getitem__) if candidates else None

    def _remove(self, key: str) -> SolveSession:
        self._last_used.pop(key, None)
        return self._sessions.pop(key)
