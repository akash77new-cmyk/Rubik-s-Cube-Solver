"""Accounts (Phase 9): sign up, log in, delete, and each account's own settings.

How passwords are kept:

- **Never stored as typed.** ``generate_password_hash`` (Werkzeug, part of Flask) stores a
  salted **scrypt** hash: a random salt per password, and a deliberately slow, memory-hungry
  function, so a stolen table can't be reversed with precomputed tables or cracked quickly.
- **Checked in constant time** by ``check_password_hash``.
- **Same answer, same time, for a wrong email and a wrong password.** A login for an
  unknown email still checks a dummy hash, so nobody can learn which emails have accounts
  by timing the reply ("user enumeration").

This module only talks to the database. Tokens (JWT) are made and checked by the web
server (``backend/server/auth.py``), which is the only place a request comes in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from backend.db.database import Database, StorageError
from backend.db.models import AIRunRow, AIStepRow, SolveRow, UserRow

MIN_PASSWORD = 8
MAX_PASSWORD = 128  # long enough for passphrases, short enough to bound the hashing work
MAX_EMAIL = 254
#: Good enough to catch typos; the only real proof of an email is sending a mail to it.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
#: Checked when the email is unknown, so both failures take the same time.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


class AccountError(ValueError):
    """A sign-up or login that can't go ahead; the message is safe to show the user."""


@dataclass(frozen=True)
class Account:
    id: int
    email: str

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "email": self.email}


def normalise_email(email: str) -> str:
    return str(email or "").strip().lower()


def check_new_credentials(email: str, password: str) -> str:
    """The normalised email, or AccountError saying what's wrong (sign-up rules)."""
    email = normalise_email(email)
    if not email or len(email) > MAX_EMAIL or not EMAIL_PATTERN.match(email):
        raise AccountError("Enter a valid email address.")
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > MAX_PASSWORD:
        raise AccountError(f"Use a password of at most {MAX_PASSWORD} characters.")
    return email


class AccountStore:
    """Accounts in the ``users`` table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------------
    def create(self, email: str, password: str) -> Account:
        """A new account. Raises AccountError (bad input, email taken) or StorageError."""
        email = check_new_credentials(email, password)
        password_hash = generate_password_hash(password)  # slow on purpose: do it outside the transaction
        try:
            with self._db.transaction("create the account") as session:
                if session.scalar(select(UserRow.id).where(UserRow.email == email)) is not None:
                    raise AccountError("An account with this email already exists. Log in instead.")
                row = UserRow(email=email, password_hash=password_hash, last_login_at=_now())
                session.add(row)
                session.flush()  # assigns row.id
                return Account(row.id, row.email)
        except StorageError as exc:
            if isinstance(exc.__cause__, IntegrityError):  # two sign-ups for one email at the same moment
                raise AccountError("An account with this email already exists. Log in instead.") from exc
            raise

    def authenticate(self, email: str, password: str) -> Optional[Account]:
        """The account if the email and password match, else None (never says which was wrong)."""
        email = normalise_email(email)
        if not isinstance(password, str) or len(password) > MAX_PASSWORD:
            check_password_hash(_DUMMY_HASH, "x")
            return None
        with self._db.transaction("check the login") as session:
            row = session.scalar(select(UserRow).where(UserRow.email == email))
            if row is None:
                check_password_hash(_DUMMY_HASH, password)  # same work as a real check
                return None
            if not check_password_hash(row.password_hash, password):
                return None
            row.last_login_at = _now()
            return Account(row.id, row.email)

    def get(self, user_id: int) -> Optional[Account]:
        with self._db.transaction("load the account") as session:
            row = session.get(UserRow, int(user_id))
            return Account(row.id, row.email) if row is not None else None

    def delete(self, user_id: int, password: str) -> bool:
        """Delete the account and everything it owns, if the password is right."""
        with self._db.transaction("delete the account") as session:
            row = session.get(UserRow, int(user_id))
            if row is None or not check_password_hash(row.password_hash, str(password or "")):
                return False
            owner = f"u:{row.id}"
            runs = select(AIRunRow.id).where(AIRunRow.owner == owner)
            session.execute(delete(AIStepRow).where(AIStepRow.run_id.in_(runs)))
            session.execute(delete(AIRunRow).where(AIRunRow.owner == owner))
            # Also deleted by the foreign key's ON DELETE CASCADE on Postgres; SQLite doesn't
            # enforce foreign keys by default, so do it explicitly on both.
            session.execute(delete(SolveRow).where(SolveRow.user_id == row.id))
            session.delete(row)
            return True

    # ------------------------------------------------------------------
    def load_settings(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._db.transaction("load the account's settings") as session:
            row = session.get(UserRow, int(user_id))
            return dict(row.settings) if row is not None and row.settings else None

    def save_settings(self, user_id: int, data: Dict[str, Any]) -> None:
        with self._db.transaction("save the account's settings") as session:
            row = session.get(UserRow, int(user_id))
            if row is not None:
                row.settings = dict(data)

    def count(self) -> int:
        with self._db.transaction("count accounts") as session:
            return len(session.scalars(select(UserRow.id)).all())


def _now() -> datetime:
    return datetime.now(timezone.utc)
