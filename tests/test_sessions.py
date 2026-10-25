"""One session per visitor (Phase 9): isolation, the shared camera, idle sessions, stores."""

import pytest

from backend.core.solver import SolverEngine
from backend.db import connect
from backend.services.accounts import AccountStore
from backend.services.analytics import AnalyticsStore
from backend.services.logbus import LogBus
from backend.services.profiles import ProfileStore
from backend.services.sessions import (
    CameraGuard,
    SessionManager,
    SharedServices,
    Visitor,
    build_session,
    visitor_from,
)
from backend.services.settings import AccountSettings, MemorySettings, SettingsStore


def shared(production=False):
    database = connect("sqlite://")
    events = []
    services = SharedServices(
        settings=SettingsStore(database),
        profiles=ProfileStore(database),
        solver=SolverEngine(),
        logs=LogBus(),
        accounts=AccountStore(database),
        database=database,
        local_analytics=AnalyticsStore(database),
        publish=lambda event, data, to=None: events.append((event, to)),
        publish_frame=lambda jpeg: None,
        production=production,
    )
    return services, events


def manager_for(services, **kwargs):
    return SessionManager(lambda visitor, guard: build_session(visitor, guard, services), **kwargs)


def test_the_engine_only_accepts_well_formed_session_keys():
    assert visitor_from({"session": "u:12", "user": {"id": 12, "email": "a@b.co"}}) == Visitor("u:12", "a@b.co")
    assert visitor_from({"session": "g:9f2c0a1b2c3d4e5f"}).user_id is None
    assert visitor_from({}).key == "local"
    assert visitor_from({"session": "u:12; DROP TABLE users"}).key == "local"
    assert visitor_from({"session": "g:abc", "user": {"email": "x@y.z"}}).email is None  # emails only for accounts


def test_two_visitors_never_share_a_cube():
    services, events = shared()
    sessions = manager_for(services)
    alice, bob = sessions.get(Visitor("g:aaaaaaaaaaaaaaaa")), sessions.get(Visitor("g:bbbbbbbbbbbbbbbb"))
    assert sessions.get(Visitor("g:aaaaaaaaaaaaaaaa")) is alice and alice is not bob and len(sessions) == 2
    alice.handle_command("cube.scramble", {"length": 20})
    assert alice.snapshot()["cubeSource"] == "scramble" and bob.snapshot()["cube"] is None
    assert ("state", "g:aaaaaaaaaaaaaaaa") in events  # events go back addressed to the visitor
    assert all(to == "g:aaaaaaaaaaaaaaaa" for _, to in events)


def test_one_camera_one_user_at_a_time():
    changes = []
    guard = CameraGuard(on_change=changes.append)
    assert guard.claim("u:1") and guard.claim("u:1") and not guard.claim("u:2")
    guard.release("u:2")  # not theirs: nothing happens
    assert guard.owner == "u:1"
    guard.release("u:1")
    assert guard.owner is None and guard.claim("u:2")
    assert changes == ["u:1", None, "u:2"]

    services, _ = shared()
    sessions = manager_for(services)
    sessions.camera.claim("u:1")
    other = sessions.get(Visitor("g:bbbbbbbbbbbbbbbb"))
    assert other.handle_command("camera.start", {}) == {"ok": False, "error": "The camera is in use by another session."}


def test_idle_sessions_close_and_the_camera_users_and_open_tabs_stay():
    services, _ = shared()
    now = [0.0]
    sessions = manager_for(services, clock=lambda: now[0], idle_seconds=60, max_sessions=3)
    for name in "abc":
        sessions.get(Visitor(f"g:{name * 16}"))
        now[0] += 10
    sessions.camera.claim(f"g:{'a' * 16}")
    sessions.get(Visitor(f"g:{'d' * 16}"))  # a 4th: the least recently used one goes (not the camera's)
    assert sorted(sessions.keys()) == [f"g:{n * 16}" for n in "acd"]
    now[0] += 120
    sessions.touch(f"g:{'d' * 16}")  # the web server: this visitor still has a tab open
    sessions.touch(f"g:{'z' * 16}")  # unknown: touching never creates a session
    assert sessions.prune() == [f"g:{'c' * 16}"]
    assert sorted(sessions.keys()) == [f"g:{n * 16}" for n in "ad"]  # using the camera; a tab open


def test_a_guest_on_the_live_site_changes_nothing_shared():
    services, _ = shared(production=True)
    guest = manager_for(services).get(Visitor("g:aaaaaaaaaaaaaaaa"))
    assert isinstance(guest._settings, MemorySettings)
    guest.handle_command("settings.update", {"theme": "light"})
    assert services.settings.current.theme == "dark"  # the installation's settings didn't change
    guest.handle_command("calibration.start", {})
    result = guest.handle_command("calibration.save", {"name": "mine"})
    assert result["ok"] is False and "Log in" in result["error"]
    assert guest._analytics is not services.local_analytics


def test_locally_a_guest_keeps_the_laptops_settings_and_history():
    services, _ = shared(production=False)
    guest = manager_for(services).get(Visitor("g:aaaaaaaaaaaaaaaa"))
    assert guest._settings is services.settings and guest._analytics is services.local_analytics


@pytest.mark.parametrize("production", [False, True])
def test_an_account_gets_its_own_saved_settings_and_history(production):
    services, _ = shared(production)
    account = services.accounts.create("akash@example.com", "cube-solver-123")
    session = manager_for(services).get(Visitor(f"u:{account.id}", account.email))
    assert isinstance(session._settings, AccountSettings) and session._analytics.user_id == account.id
    assert session._can_save_shared is True


def test_a_deleted_accounts_old_token_gets_a_guest_session():
    services, _ = shared(production=True)
    session = manager_for(services).get(Visitor("u:999"))  # no such account (deleted on another device)
    assert isinstance(session._settings, MemorySettings) and session._analytics.user_id is None
