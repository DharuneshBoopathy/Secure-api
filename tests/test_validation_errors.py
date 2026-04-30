"""
Pydantic validation error tests for schemas not covered by test_schema_hardening.py.

Covers:
  LoginIn        — username/password length bounds
  RegisterIn     — username pattern, email pattern, password length
  TokenRefreshIn — minimum token length
  ChangePasswordIn — password length bounds
  AdminCreateUserIn — role enum constraint
  ShadowAcknowledgeIn — reason min/max length
  ZombieActionIn      — reason min/max length
"""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AdminCreateUserIn,
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    ShadowAcknowledgeIn,
    TokenRefreshIn,
    ZombieActionIn,
)


# ---------------------------------------------------------------------------
# LoginIn
# ---------------------------------------------------------------------------

def test_login_rejects_username_too_short():
    with pytest.raises(ValidationError):
        LoginIn(username="ab", password="ValidPass1!")


def test_login_rejects_password_too_short():
    with pytest.raises(ValidationError):
        LoginIn(username="validuser", password="short")


def test_login_accepts_valid_credentials():
    body = LoginIn(username="alice", password="P@ssw0rd!")
    assert body.username == "alice"


def test_login_rejects_username_over_128_chars():
    with pytest.raises(ValidationError):
        LoginIn(username="a" * 129, password="P@ssw0rd!")


def test_login_rejects_password_over_256_chars():
    with pytest.raises(ValidationError):
        LoginIn(username="alice", password="A1!" + "x" * 254)


# ---------------------------------------------------------------------------
# RegisterIn
# ---------------------------------------------------------------------------

def test_register_rejects_username_with_spaces():
    with pytest.raises(ValidationError):
        RegisterIn(username="bad user", password="P@ssw0rd!", email="a@b.com")


def test_register_rejects_username_with_special_chars():
    with pytest.raises(ValidationError):
        RegisterIn(username="user<script>", password="P@ssw0rd!", email="a@b.com")


def test_register_rejects_invalid_email_no_at():
    with pytest.raises(ValidationError):
        RegisterIn(username="alice", password="P@ssw0rd!", email="notanemail")


def test_register_rejects_invalid_email_no_domain():
    with pytest.raises(ValidationError):
        RegisterIn(username="alice", password="P@ssw0rd!", email="alice@")


def test_register_rejects_password_too_short():
    with pytest.raises(ValidationError):
        RegisterIn(username="alice", password="short", email="a@b.com")


def test_register_accepts_valid_payload():
    body = RegisterIn(username="alice_99", password="P@ssw0rd!123X", email="alice@example.com")
    assert body.username == "alice_99"
    assert body.email == "alice@example.com"


def test_register_accepts_username_with_dots_hyphens():
    body = RegisterIn(username="alice.bob-99", password="P@ssw0rd!123X", email="a@b.com")
    assert body.username == "alice.bob-99"


def test_register_rejects_username_too_short():
    with pytest.raises(ValidationError):
        RegisterIn(username="ab", password="P@ssw0rd!", email="a@b.com")


# ---------------------------------------------------------------------------
# TokenRefreshIn
# ---------------------------------------------------------------------------

def test_token_refresh_rejects_too_short_token():
    with pytest.raises(ValidationError):
        TokenRefreshIn(refresh_token="short")


def test_token_refresh_accepts_valid_length():
    token = "a" * 10  # min_length=10
    body = TokenRefreshIn(refresh_token=token)
    assert len(body.refresh_token) >= 10


# ---------------------------------------------------------------------------
# ChangePasswordIn
# ---------------------------------------------------------------------------

def test_change_password_rejects_current_too_short():
    with pytest.raises(ValidationError):
        ChangePasswordIn(current_password="tiny", new_password="P@ssw0rd!")


def test_change_password_rejects_new_too_short():
    with pytest.raises(ValidationError):
        ChangePasswordIn(current_password="P@ssw0rd!", new_password="tiny")


def test_change_password_accepts_valid_payload():
    body = ChangePasswordIn(current_password="OldP@ss1!", new_password="NewP@ss2!xxxX1")
    assert body.current_password == "OldP@ss1!"


def test_change_password_rejects_current_over_256_chars():
    with pytest.raises(ValidationError):
        ChangePasswordIn(current_password="A1!" + "x" * 254, new_password="P@ssw0rd!")


# ---------------------------------------------------------------------------
# AdminCreateUserIn
# ---------------------------------------------------------------------------

def test_admin_create_rejects_invalid_role():
    with pytest.raises(ValidationError):
        AdminCreateUserIn(
            username="bob", password="P@ssw0rd!", email="b@b.com", role="superuser"
        )


def test_admin_create_accepts_admin_role():
    body = AdminCreateUserIn(username="bob", password="P@ssw0rd!123X", email="b@b.com", role="admin")
    assert body.role == "admin"


def test_admin_create_accepts_editor_role():
    body = AdminCreateUserIn(username="bob", password="P@ssw0rd!123X", email="b@b.com", role="editor")
    assert body.role == "editor"


def test_admin_create_accepts_viewer_role():
    body = AdminCreateUserIn(username="bob", password="P@ssw0rd!123X", email="b@b.com", role="viewer")
    assert body.role == "viewer"


def test_admin_create_rejects_username_with_injection_chars():
    with pytest.raises(ValidationError):
        AdminCreateUserIn(
            username="bob'; DROP TABLE users;--",
            password="P@ssw0rd!",
            email="b@b.com",
        )


# ---------------------------------------------------------------------------
# ShadowAcknowledgeIn
# ---------------------------------------------------------------------------

def test_shadow_ack_rejects_reason_too_short():
    with pytest.raises(ValidationError):
        ShadowAcknowledgeIn(reason="ab")  # min_length=3


def test_shadow_ack_accepts_reason_at_minimum():
    body = ShadowAcknowledgeIn(reason="ok.")
    assert len(body.reason) >= 3


def test_shadow_ack_rejects_reason_over_512_chars():
    with pytest.raises(ValidationError):
        ShadowAcknowledgeIn(reason="a" * 513)


def test_shadow_ack_accepts_reason_at_maximum():
    body = ShadowAcknowledgeIn(reason="a" * 512)
    assert len(body.reason) == 512


# ---------------------------------------------------------------------------
# ZombieActionIn
# ---------------------------------------------------------------------------

def test_zombie_action_rejects_reason_too_short():
    with pytest.raises(ValidationError):
        ZombieActionIn(reason="ab")


def test_zombie_action_accepts_reason_at_minimum():
    body = ZombieActionIn(reason="ok.")
    assert len(body.reason) >= 3


def test_zombie_action_rejects_reason_over_512_chars():
    with pytest.raises(ValidationError):
        ZombieActionIn(reason="z" * 513)


def test_zombie_action_accepts_reason_at_maximum():
    body = ZombieActionIn(reason="z" * 512)
    assert len(body.reason) == 512
