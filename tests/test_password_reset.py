"""
Password reset ("forgot password") flow tests.

Covers:
  1. Requesting a reset for a known email always returns the generic response.
  2. Requesting a reset for an unknown email returns the same generic response
     (no account enumeration) and creates no token.
  3. A valid token resets the password and the new password can log in.
  4. A used token cannot be replayed.
  5. An expired token is rejected.
  6. An unknown token is rejected.
  7. A weak new password is rejected (422) and does not consume the token.
  8. Completing a reset revokes all outstanding refresh tokens.
  9. Completing a reset invalidates other outstanding reset tokens for the same user.
"""

import re
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base, PasswordResetToken, RefreshToken, User
from app.routers.auth import confirm_password_reset as _confirm_wrapped
from app.routers.auth import request_password_reset as _request_wrapped
from app.schemas import PasswordResetConfirmIn, PasswordResetRequestIn
from app.security import create_refresh_token, hash_password, hash_token, utc_now, verify_password

_request_reset = _request_wrapped.__wrapped__
_confirm_reset = _confirm_wrapped.__wrapped__


class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

_TABLES = [User.__table__, RefreshToken.__table__, PasswordResetToken.__table__, AuditLog.__table__]
OLD_PASSWORD = "OldP@ssw0rd1!"
NEW_PASSWORD = "NewP@ssw0rd2!"


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
        email="alice@example.com",
        password_hash=hash_password(OLD_PASSWORD),
        role="viewer",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _request(db, email: str):
    return _request_reset(request=FAKE_REQUEST, body=PasswordResetRequestIn(email=email), db=db)


def _confirm(db, token: str, new_password: str):
    return _confirm_reset(
        request=FAKE_REQUEST, body=PasswordResetConfirmIn(token=token, new_password=new_password), db=db
    )


def _issue_token(db, user_id: int, *, expired: bool = False, used: bool = False) -> str:
    raw = "raw-reset-token-" + str(user_id) + ("-x" if expired else "")
    expires = utc_now() + (timedelta(minutes=-1) if expired else timedelta(minutes=30))
    db.add(PasswordResetToken(user_id=user_id, token=hash_token(raw), expires_at=expires, used=used))
    db.commit()
    return raw


def test_request_known_email_returns_generic_message(db, user):
    result = _request(db, "alice@example.com")
    assert "message" in result
    tokens = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).all()
    assert len(tokens) == 1


def test_request_unknown_email_returns_same_generic_message_and_no_token(db):
    result = _request(db, "nobody@example.com")
    assert "message" in result
    assert db.query(PasswordResetToken).count() == 0


def test_reset_token_is_never_logged_in_production(db, user, caplog, monkeypatch):
    """Application logs are routinely shipped to a SIEM, so a reset token in
    that stream is an account-takeover primitive for everyone with log read
    access. Until a real delivery transport exists, production must record the
    request and discard the token."""
    import logging

    import app.routers.auth as auth_module
    from app.config import Settings

    monkeypatch.setattr(auth_module, "get_settings", lambda: Settings(_env_file=None, app_env="production"))
    with caplog.at_level(logging.DEBUG):
        _request(db, "alice@example.com")

    # The token still exists (the flow works); it just isn't in the logs.
    row = db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id).one()
    assert row.token
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "alice" in text, "the request itself should still be recorded"
    assert "out-of-band" not in text
    # No 32-byte urlsafe token-shaped string should appear anywhere.
    assert not re.search(r"[A-Za-z0-9_-]{40,}", text), f"possible token leaked into logs: {text!r}"


def test_reset_email_is_sent_when_a_transport_is_configured(db, user, caplog, monkeypatch):
    import logging

    import app.routers.auth as auth_module

    sent = {}
    monkeypatch.setattr(auth_module.mailer, "is_configured", lambda: True)
    monkeypatch.setattr(
        auth_module.mailer,
        "send_password_reset",
        lambda **kw: sent.update(kw),
    )
    with caplog.at_level(logging.DEBUG):
        _request(db, "alice@example.com")

    assert sent["to"] == "alice@example.com"
    assert sent["username"] == "alice"
    assert sent["token"], "the token has to reach the mailer"
    # ...and nowhere else.
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert sent["token"] not in text


def test_delivery_failure_does_not_change_the_response(db, user, monkeypatch):
    """The response is identical for known and unknown addresses on purpose.
    Surfacing a send failure would leak which addresses are registered."""
    import app.routers.auth as auth_module

    def _boom(**_kw):
        raise RuntimeError("smtp unreachable")

    monkeypatch.setattr(auth_module.mailer, "is_configured", lambda: True)
    monkeypatch.setattr(auth_module.mailer, "send_password_reset", _boom)

    known = _request(db, "alice@example.com")
    unknown = _request(db, "nobody@example.com")
    assert known == unknown


def test_reset_token_is_logged_outside_production_for_local_dev(db, user, caplog, monkeypatch):
    import logging

    import app.routers.auth as auth_module
    from app.config import Settings

    monkeypatch.setattr(auth_module, "get_settings", lambda: Settings(_env_file=None, app_env="development"))
    with caplog.at_level(logging.DEBUG):
        _request(db, "alice@example.com")
    assert "DEV ONLY" in "\n".join(r.getMessage() for r in caplog.records)


def test_valid_token_resets_password_and_new_password_works(db, user):
    raw = _issue_token(db, user.id)
    _confirm(db, raw, NEW_PASSWORD)
    db.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert not verify_password(OLD_PASSWORD, user.password_hash)


def test_used_token_cannot_be_replayed(db, user):
    raw = _issue_token(db, user.id)
    _confirm(db, raw, NEW_PASSWORD)
    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, raw, "AnotherP@ss3!")
    assert exc_info.value.status_code == 400


def test_expired_token_rejected(db, user):
    raw = _issue_token(db, user.id, expired=True)
    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, raw, NEW_PASSWORD)
    assert exc_info.value.status_code == 400


def test_unknown_token_rejected(db, user):
    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, "never-issued-token", NEW_PASSWORD)
    assert exc_info.value.status_code == 400


def test_weak_new_password_rejected_and_token_not_consumed(db, user):
    """Long enough to pass schema length bounds but fails validate_password_strength (no upper/digit/special)."""
    raw = _issue_token(db, user.id)
    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, raw, "alllowercaseonly")
    assert exc_info.value.status_code == 422
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token == hash_token(raw)).one()
    assert row.used is False


def test_confirm_revokes_all_refresh_tokens(db, user):
    raw_refresh, exp = create_refresh_token("alice")
    db.add(RefreshToken(user_id=user.id, token=hash_token(raw_refresh), expires_at=exp, revoked=False))
    db.commit()

    raw_reset = _issue_token(db, user.id)
    _confirm(db, raw_reset, NEW_PASSWORD)

    active = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
        .count()
    )
    assert active == 0


def test_confirm_invalidates_other_outstanding_reset_tokens(db, user):
    raw_a = _issue_token(db, user.id)
    raw_b = "raw-reset-token-second"
    db.add(
        PasswordResetToken(
            user_id=user.id, token=hash_token(raw_b), expires_at=utc_now() + timedelta(minutes=30), used=False
        )
    )
    db.commit()

    _confirm(db, raw_a, NEW_PASSWORD)

    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, raw_b, "AnotherP@ss3!")
    assert exc_info.value.status_code == 400
