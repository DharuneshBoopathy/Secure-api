"""
TOTP MFA tests (admin accounts only).

Covers:
  1. An admin with MFA not enrolled logs in with password alone.
  2. Enrollment issues a secret but leaves mfa_enabled False until confirmed.
  3. Confirming with a wrong code does not enable MFA.
  4. Confirming with a valid code enables MFA.
  5. Once enabled, login without a code is rejected (code required).
  6. Once enabled, login with a wrong code is rejected and counts as a failed
     login attempt (lockout interaction).
  7. Once enabled, login with a valid code succeeds.
  8. Disabling requires a valid code; a wrong code is rejected.
  9. A valid code disables MFA and clears the stored secret.
  10. A non-admin cannot enroll (403).
  11. MFA enforcement does not apply to non-admin roles even if mfa_enabled
      were somehow set.
"""

import pyotp
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import require_role
from app.models import AuditLog, Base, RefreshToken, User
from app.routers.auth import login as _login_wrapped
from app.routers.auth import mfa_disable as _mfa_disable_wrapped
from app.routers.auth import mfa_enroll as _mfa_enroll_wrapped
from app.routers.auth import mfa_enroll_confirm as _mfa_confirm_wrapped
from app.schemas import LoginIn, MfaCodeIn
from app.security import Role, hash_password

_login = _login_wrapped.__wrapped__
_mfa_enroll = _mfa_enroll_wrapped.__wrapped__
_mfa_confirm = _mfa_confirm_wrapped.__wrapped__
_mfa_disable = _mfa_disable_wrapped.__wrapped__


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
PASSWORD = "AdminP@ssw0rd1!"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def admin(db):
    u = User(username="root", password_hash=hash_password(PASSWORD), role="admin", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def viewer(db):
    u = User(username="alice", password_hash=hash_password(PASSWORD), role="viewer", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login_as(db, username: str, code: str | None = None):
    return _login(request=FAKE_REQUEST, body=LoginIn(username=username, password=PASSWORD, mfa_code=code), db=db)


def _enroll(db, user):
    return _mfa_enroll(request=FAKE_REQUEST, current_user=user, db=db)


def _confirm(db, user, code: str):
    return _mfa_confirm(request=FAKE_REQUEST, body=MfaCodeIn(code=code), current_user=user, db=db)


def _disable(db, user, code: str):
    return _mfa_disable(request=FAKE_REQUEST, body=MfaCodeIn(code=code), current_user=user, db=db)


def _enable_mfa(db, admin) -> str:
    """Enroll + confirm; return the raw secret for generating codes in tests."""
    enrolled = _enroll(db, admin)
    _confirm(db, admin, pyotp.TOTP(enrolled.secret).now())
    db.refresh(admin)
    return enrolled.secret


def test_login_without_enrollment_needs_only_password(db, admin):
    result = _login_as(db, "root")
    assert result.user.username == "root"


def test_enroll_generates_secret_but_leaves_disabled(db, admin):
    out = _enroll(db, admin)
    db.refresh(admin)
    assert admin.mfa_secret == out.secret
    assert admin.mfa_enabled is False
    assert out.otpauth_uri.startswith("otpauth://totp/")


def test_confirm_with_wrong_code_does_not_enable(db, admin):
    _enroll(db, admin)
    with pytest.raises(HTTPException) as exc_info:
        _confirm(db, admin, "000000")
    assert exc_info.value.status_code == 400
    db.refresh(admin)
    assert admin.mfa_enabled is False


def test_confirm_with_valid_code_enables_mfa(db, admin):
    secret = _enable_mfa(db, admin)
    db.refresh(admin)
    assert admin.mfa_enabled is True
    assert admin.mfa_secret == secret


def test_login_without_code_rejected_once_enabled(db, admin):
    _enable_mfa(db, admin)
    with pytest.raises(HTTPException) as exc_info:
        _login_as(db, "root")
    assert exc_info.value.status_code == 401
    assert "MFA code required" in exc_info.value.detail


def test_login_with_wrong_code_rejected_and_counts_as_failure(db, admin):
    _enable_mfa(db, admin)
    with pytest.raises(HTTPException) as exc_info:
        _login_as(db, "root", code="000000")
    assert exc_info.value.status_code == 401
    assert "Invalid MFA code" in exc_info.value.detail
    db.refresh(admin)
    assert admin.failed_login_count == 1


def test_login_with_valid_code_succeeds(db, admin):
    secret = _enable_mfa(db, admin)
    code = pyotp.TOTP(secret).now()
    result = _login_as(db, "root", code=code)
    assert result.user.username == "root"


def test_disable_requires_valid_code(db, admin):
    secret = _enable_mfa(db, admin)
    with pytest.raises(HTTPException) as exc_info:
        _disable(db, admin, "000000")
    assert exc_info.value.status_code == 400
    db.refresh(admin)
    assert admin.mfa_enabled is True
    assert admin.mfa_secret == secret


def test_disable_with_valid_code_clears_secret(db, admin):
    secret = _enable_mfa(db, admin)
    _disable(db, admin, pyotp.TOTP(secret).now())
    db.refresh(admin)
    assert admin.mfa_enabled is False
    assert admin.mfa_secret is None
    # Login now needs password only again.
    result = _login_as(db, "root")
    assert result.user.username == "root"


def test_non_admin_cannot_enroll(db, viewer):
    check = require_role(Role.ADMIN)
    with pytest.raises(HTTPException) as exc_info:
        check(current_user=viewer)
    assert exc_info.value.status_code == 403


def test_viewer_role_never_prompted_for_mfa_even_if_flag_set(db, viewer):
    """Defense-in-depth: login enforcement is gated on role == admin, not just mfa_enabled."""
    viewer.mfa_enabled = True
    viewer.mfa_secret = pyotp.random_base32()
    db.commit()
    result = _login_as(db, "alice")
    assert result.user.username == "alice"
