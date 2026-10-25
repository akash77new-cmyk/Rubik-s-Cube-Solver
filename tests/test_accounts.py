"""Accounts (Phase 9): passwords, sign-up rules, deletion, and each account's own data."""

import pytest
from sqlalchemy import select

import backend.services.accounts as accounts_module
from backend.ai.tracing import Trace, TraceStore
from backend.config import Settings
from backend.db import connect
from backend.db.models import SolveRow, UserRow
from backend.services.accounts import AccountError, AccountStore
from backend.services.analytics import AnalyticsStore, SolveRecord
from backend.services.settings import AccountSettings, MemorySettings, SettingsStore


def solve(number: int) -> SolveRecord:
    return SolveRecord(
        id=f"solve-{number}", started_at=1000.0 + number, finished_at=1010.0 + number, move_count=20 + number,
        quarter_turns=24, solve_ms=5.0, scan_seconds=30.0, execution_seconds=40.0, backend="test",
        notation="R U", source="scramble",
    )


@pytest.fixture
def store():
    database = connect("sqlite://")
    return database, AccountStore(database)


def test_sign_up_and_log_in_with_a_hashed_password(store):
    database, accounts = store
    account = accounts.create("  Akash@Example.COM ", "cube-solver-123")
    assert account.email == "akash@example.com"  # one account per address, whatever the case
    with database.transaction("read") as session:
        stored = session.scalar(select(UserRow.password_hash))
    assert stored.startswith("scrypt:") and "cube-solver-123" not in stored  # a salted hash, never the password
    assert accounts.authenticate("AKASH@example.com", "cube-solver-123") == account
    assert accounts.authenticate("akash@example.com", "wrong-password") is None
    assert accounts.authenticate("nobody@example.com", "cube-solver-123") is None


def test_an_unknown_email_costs_the_same_password_check(store, monkeypatch):
    _, accounts = store
    accounts.create("akash@example.com", "cube-solver-123")
    checks = []
    real = accounts_module.check_password_hash
    monkeypatch.setattr(accounts_module, "check_password_hash", lambda h, p: checks.append(h) or real(h, p))
    accounts.authenticate("nobody@example.com", "whatever-123")
    accounts.authenticate("akash@example.com", "whatever-123")
    assert len(checks) == 2  # one hash check each: the reply time doesn't reveal which emails exist


@pytest.mark.parametrize(
    "email, password, message",
    [
        ("not-an-email", "cube-solver-123", "valid email"),
        ("a@b.co", "short", "at least 8"),
        ("a@b.co", "x" * 129, "at most 128"),
    ],
)
def test_sign_up_rules(store, email, password, message):
    _, accounts = store
    with pytest.raises(AccountError, match=message):
        accounts.create(email, password)


def test_one_account_per_email(store):
    _, accounts = store
    accounts.create("akash@example.com", "cube-solver-123")
    with pytest.raises(AccountError, match="already exists"):
        accounts.create("AKASH@example.com", "another-password")


def test_deleting_an_account_removes_its_history_and_traces(store):
    database, accounts = store
    keep = accounts.create("keep@example.com", "cube-solver-123")
    gone = accounts.create("gone@example.com", "cube-solver-123")
    AnalyticsStore(database, keep.id).record(solve(1))
    AnalyticsStore(database, gone.id).record(solve(2))
    traces = TraceStore(database)
    for owner in (f"u:{keep.id}", f"u:{gone.id}"):
        trace = Trace(f"run-{owner}", "assistant", "How many moves?", owner=owner)
        trace.finish("fallback", {"answer": "ok"}, None, None)
        traces.save(trace)

    assert accounts.delete(gone.id, "wrong-password") is False
    assert accounts.delete(gone.id, "cube-solver-123") is True
    assert accounts.get(gone.id) is None and accounts.get(keep.id) == keep
    with database.transaction("read") as session:
        owners = session.scalars(select(SolveRow.user_id)).all()
    assert owners == [keep.id]
    assert [run["id"] for run in traces.recent()] == [f"run-u:{keep.id}"]


def test_each_account_has_its_own_history(store):
    database, accounts = store
    first = accounts.create("first@example.com", "cube-solver-123")
    second = accounts.create("second@example.com", "cube-solver-123")
    AnalyticsStore(database, first.id).record(solve(1))
    AnalyticsStore(database, first.id).record(solve(2))
    AnalyticsStore(database, None).record(solve(3))  # made without an account
    assert AnalyticsStore(database, first.id).summary()["totalSolves"] == 2  # reloaded from the database
    assert AnalyticsStore(database, second.id).summary()["totalSolves"] == 0
    assert AnalyticsStore(database, None).summary()["totalSolves"] == 1
    AnalyticsStore(database, first.id).clear()  # clears only that account's history
    assert AnalyticsStore(database, None).summary()["totalSolves"] == 1


def test_a_guests_history_and_settings_live_in_memory_only(store):
    database, _ = store
    guest = AnalyticsStore(None)
    guest.record(solve(1))
    assert guest.summary()["totalSolves"] == 1
    assert AnalyticsStore(database, None).summary()["totalSolves"] == 0  # nothing reached the database
    installation = SettingsStore(database)
    visit = MemorySettings(installation.current)
    visit.update({"theme": "light"})
    assert visit.current.theme == "light" and installation.current.theme == "dark"


def test_an_accounts_settings_are_saved_to_its_row(store):
    database, accounts = store
    account = accounts.create("akash@example.com", "cube-solver-123")
    seed = Settings.from_dict({**Settings().to_dict(), "theme": "midnight"})
    settings = AccountSettings(accounts, account.id, seed)
    assert settings.current.theme == "midnight"  # a new account starts from the installation's settings
    settings.update({"theme": "light", "not_a_setting": 1})
    assert AccountSettings(accounts, account.id, Settings()).current.theme == "light"  # saved
    assert SettingsStore(database).current.theme == "dark"  # the installation's row is untouched
