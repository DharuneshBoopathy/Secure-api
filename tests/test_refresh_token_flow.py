"""
Integration tests for the refresh token lifecycle (DB-backed).

Covers:
  1. A valid refresh token issues new access + refresh tokens.
  2. Token rotation: the consumed token row is marked revoked.
  3. The new refresh token is stored (hashed) in the DB as a fresh row.
  4. Replay attack: reusing an already-consumed token returns 401.
  5. A pre-revoked token returns 401.
  6. An expired token returns 401.
  7. Submitting an access token where a refresh token is expected returns 401.
  8. A JWT that was never inserted into the DB returns 401.
  9. Logout marks the token revoked.
  10. Using a refresh token after logout returns 401.
  11. Logout of a non-existent token is a no-op (returns {"logged_out": True}).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base, RefreshToken, User
from app.routers.auth import logout as _logout_wrapped
from app.routers.auth import refresh as _refresh_wrapped
from app.schemas import TokenRefreshIn
from app.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
)

# Bypass the slowapi rate-limit wrapper so the limiter's in-memory counter
# does not accumulate across tests and cause spurious 429s.
_refresh = _refresh_wrapped.__wrapped__
_logout = _logout_wrapped.__wrapped__


# ---------------------------------------------------------------------------
# Minimal request stub
# (only fields used by log_audit_event inside the refresh route)
# ---------------------------------------------------------------------------

class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABLES = [User.__table__, RefreshToken.__table__, AuditLog.__table__]


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
    u = User(
        username="alice",
        password_hash=hash_password("P@ssw0rd!"),
        role="viewer",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _seed(db, user_id: int, *, revoked: bool = False, expired: bool = False) -> tuple[str, int]:
    """Insert one RefreshToken row; return (plaintext_jwt, row_id).

    Each call to create_refresh_token() produces a unique JWT because it
    embeds a random jti claim (RFC 7519 §4.1.7).
    """
    raw, exp = create_refresh_token("alice")
    if expired:
        exp = datetime.now(UTC) - timedelta(seconds=1)
    row = RefreshToken(user_id=user_id, token=hash_token(raw), expires_at=exp, revoked=revoked)
    db.add(row)
    db.commit()
    db.refresh(row)
    return raw, row.id


def _call_refresh(db, token_str: str):
    return _refresh(request=FAKE_REQUEST, body=TokenRefreshIn(refresh_token=token_str), db=db)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_refresh_returns_access_and_refresh_tokens(db, user):
    raw, _ = _seed(db, user.id)
    result = _call_refresh(db, raw)
    assert result.access_token
    assert result.refresh_token
    assert result.user.username == "alice"


def test_returned_refresh_token_differs_from_original(db, user):
    """jti nonce makes every token unique, so rotation always yields a new string."""
    raw, _ = _seed(db, user.id)
    result = _call_refresh(db, raw)
    assert result.refresh_token != raw


def test_token_rotation_revokes_consumed_token(db, user):
    """The original row must be marked revoked after a successful refresh."""
    raw, row_id = _seed(db, user.id)
    _call_refresh(db, raw)
    # Query by primary key to be immune to any hash-collision edge cases.
    row = db.query(RefreshToken).filter(RefreshToken.id == row_id).one()
    assert row.revoked is True


def test_new_refresh_token_stored_in_db(db, user):
    """A fresh, non-revoked row must exist after token rotation."""
    raw, old_id = _seed(db, user.id)
    result = _call_refresh(db, raw)
    new_hash = hash_token(result.refresh_token)
    new_row = db.query(RefreshToken).filter(RefreshToken.token == new_hash).one_or_none()
    assert new_row is not None
    assert new_row.id != old_id
    assert new_row.revoked is False


# ---------------------------------------------------------------------------
# Replay attack prevention
# ---------------------------------------------------------------------------

def test_replay_attack_second_use_of_same_token_returns_401(db, user):
    """The original token must be unusable after rotation (replay-attack prevention)."""
    from fastapi import HTTPException
    raw, _ = _seed(db, user.id)
    _call_refresh(db, raw)   # first use — rotates token
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw)  # second use — old token is revoked
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------

def test_pre_revoked_token_returns_401(db, user):
    from fastapi import HTTPException
    raw, _ = _seed(db, user.id, revoked=True)
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw)
    assert exc_info.value.status_code == 401


def test_expired_token_returns_401(db, user):
    from fastapi import HTTPException
    raw, _ = _seed(db, user.id, expired=True)
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw)
    assert exc_info.value.status_code == 401


def test_access_token_rejected_as_refresh_token(db, user):
    """A valid access JWT submitted in the refresh slot must be rejected."""
    from fastapi import HTTPException
    raw_access, _ = create_access_token("alice")
    # Insert a DB row so the hash lookup passes; the type-claim check must still reject.
    exp = datetime.now(UTC) + timedelta(days=7)
    db.add(RefreshToken(user_id=user.id, token=hash_token(raw_access), expires_at=exp, revoked=False))
    db.commit()
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw_access)
    assert exc_info.value.status_code == 401


def test_unknown_token_not_in_db_returns_401(db, user):
    """A well-formed JWT that was never stored in the DB must return 401."""
    from fastapi import HTTPException
    raw, _ = create_refresh_token("alice")  # valid JWT, no DB row
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_marks_token_revoked(db, user):
    raw, row_id = _seed(db, user.id)
    _logout(request=FAKE_REQUEST, body=TokenRefreshIn(refresh_token=raw), db=db)
    row = db.query(RefreshToken).filter(RefreshToken.id == row_id).one()
    assert row.revoked is True


def test_refresh_after_logout_returns_401(db, user):
    from fastapi import HTTPException
    raw, _ = _seed(db, user.id)
    _logout(request=FAKE_REQUEST, body=TokenRefreshIn(refresh_token=raw), db=db)
    with pytest.raises(HTTPException) as exc_info:
        _call_refresh(db, raw)
    assert exc_info.value.status_code == 401


def test_logout_of_nonexistent_token_is_noop(db, user):
    raw, _ = create_refresh_token("alice")  # never inserted
    result = _logout(request=FAKE_REQUEST, body=TokenRefreshIn(refresh_token=raw), db=db)
    assert result == {"logged_out": True}
