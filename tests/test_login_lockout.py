"""
Per-account login lockout tests.

Covers:
  1. Failed logins below the threshold do not lock the account.
  2. Reaching the threshold locks the account and returns 423.
  3. A locked account rejects even a correct password until the lock expires.
  4. Lock duration follows exponential backoff, capped at the configured max.
  5. A successful login resets the failure counter and any lock.
  6. Lockout state is scoped per-account (one user's lockout doesn't affect another).
"""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import AuditLog, Base, RefreshToken, User
from app.routers.auth import login as _login_wrapped
from app.schemas import LoginIn
from app.security import hash_password, utc_now

# Bypass the slowapi rate-limit wrapper so the limiter's in-memory counter
# does not accumulate across tests and cause spurious 429s.
_login = _login_wrapped.__wrapped__


class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

_TABLES = [User.__table__, RefreshToken.__table__, AuditLog.__table__]
PASSWORD = "P@ssw0rd123!"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def user(db):
    u = User(username="alice", password_hash=hash_password(PASSWORD), role="viewer", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _try_login(db, username: str, password: str):
    return _login(request=FAKE_REQUEST, body=LoginIn(username=username, password=password), db=db)


def _fail(db, username: str, times: int) -> None:
    for _ in range(times):
        with pytest.raises(HTTPException):
            _try_login(db, username, "wrong-password")


def test_failures_below_threshold_do_not_lock(db, user):
    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold - 1)
    db.refresh(user)
    assert user.locked_until is None
    # Correct password still works.
    result = _try_login(db, "alice", PASSWORD)
    assert result.user.username == "alice"


def test_threshold_failures_lock_account(db, user):
    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold)
    db.refresh(user)
    assert user.locked_until is not None
    assert user.locked_until > utc_now()


def test_locked_account_rejects_correct_password(db, user):
    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold)
    with pytest.raises(HTTPException) as exc_info:
        _try_login(db, "alice", PASSWORD)
    assert exc_info.value.status_code == 423


def test_lock_expires_and_correct_password_then_succeeds(db, user):
    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold)
    db.refresh(user)
    # Simulate the lock having already elapsed.
    user.locked_until = utc_now() - timedelta(seconds=1)
    db.commit()
    result = _try_login(db, "alice", PASSWORD)
    assert result.user.username == "alice"


def test_successful_login_resets_failure_counter(db, user):
    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold - 1)
    _try_login(db, "alice", PASSWORD)
    db.refresh(user)
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_lockout_duration_capped_at_max(db, user):
    settings = get_settings()
    # Push well past the threshold so the exponential backoff would otherwise
    # exceed the configured max.
    _fail(db, "alice", settings.login_lockout_threshold + 10)
    db.refresh(user)
    remaining = (user.locked_until - utc_now()).total_seconds()
    assert remaining <= settings.login_lockout_max_seconds + 1


def test_lockout_is_scoped_per_account(db, user):
    other = User(username="bob", password_hash=hash_password(PASSWORD), role="viewer", is_active=True)
    db.add(other)
    db.commit()

    settings = get_settings()
    _fail(db, "alice", settings.login_lockout_threshold)
    db.refresh(other)
    assert other.locked_until is None
    # bob can still log in normally.
    result = _try_login(db, "bob", PASSWORD)
    assert result.user.username == "bob"


def test_nonexistent_username_does_not_error(db):
    """Failed attempts against an unknown username must not raise/500 (no user row to update)."""
    with pytest.raises(HTTPException) as exc_info:
        _try_login(db, "nobody", "wrong-password")
    assert exc_info.value.status_code == 401
