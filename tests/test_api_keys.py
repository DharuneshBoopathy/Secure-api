"""
Per-integration API key tests.

Covers:
  1. A newly created key resolves to a user with the assigned role via
     get_current_user (X-Monitor-Key header).
  2. The plaintext key is only ever returned once, at creation.
  3. Listing keys never exposes the plaintext or a reversible hash.
  4. A revoked key stops authenticating.
  5. An unknown/garbage key is rejected.
  6. The legacy static MONITOR_API_KEY still works unchanged (backward compat).
  7. Using a key updates its last_used_at timestamp.
  8. Role is capped — admin is rejected by the schema at creation.
  9. A viewer-role key cannot pass an editor-level require_role check.
  10. An editor-role key passes an editor-level require_role check.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.deps import OrgContext, get_current_user, require_role
from app.models import ApiKey, AuditLog, Base, Organization, OrgMembership, User
from app.routers.auth import create_api_key as _create_wrapped
from app.routers.auth import revoke_api_key as _revoke_wrapped
from app.schemas import ApiKeyCreateIn
from app.security import OrgRole, Role, hash_password

_create_api_key = _create_wrapped.__wrapped__
_revoke_api_key = _revoke_wrapped


class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

_TABLES = [User.__table__, ApiKey.__table__, AuditLog.__table__, Organization.__table__, OrgMembership.__table__]


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
    # Username matches settings.admin_username (default "admin") so the
    # legacy static-MONITOR_API_KEY -> system-admin lookup resolves.
    u = User(
        username=get_settings().admin_username,
        password_hash=hash_password("AdminP@ss1!"),
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def org(db, admin):
    o = Organization(name="Default Organization", slug="default", owner_user_id=admin.id)
    db.add(o)
    db.commit()
    db.refresh(o)
    db.add(OrgMembership(user_id=admin.id, org_id=o.id, role="owner", status="active"))
    db.commit()
    return o


def _ctx(org) -> OrgContext:
    return OrgContext(org_id=org.id, role=OrgRole.OWNER)


def _issue(db, admin, org, name: str = "ci-integration", role: str = "editor"):
    return _create_api_key(
        request=FAKE_REQUEST, body=ApiKeyCreateIn(name=name, role=role), admin=admin, ctx=_ctx(org), db=db
    )


def test_new_key_resolves_via_get_current_user(db, admin, org):
    created = _issue(db, admin, org, role="editor")
    user = get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    assert user.role == "editor"
    assert user.username == f"apikey:{created.name}"


def test_plaintext_only_returned_at_creation(db, admin, org):
    created = _issue(db, admin, org)
    row = db.query(ApiKey).filter(ApiKey.id == created.id).one()
    assert created.api_key not in (row.key_hash, row.key_prefix)
    assert row.key_hash != created.api_key


def test_list_never_exposes_secret(db, admin, org):
    from app.routers.auth import list_api_keys

    _issue(db, admin, org)
    rows = list_api_keys(ctx=_ctx(org), db=db)
    for r in rows:
        assert not hasattr(r, "api_key")
        assert not hasattr(r, "key_hash")


def test_revoked_key_stops_authenticating(db, admin, org):
    created = _issue(db, admin, org)
    _revoke_api_key(request=FAKE_REQUEST, key_id=created.id, admin=admin, ctx=_ctx(org), db=db)
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    assert exc_info.value.status_code == 401


def test_unknown_key_rejected(db, admin, org):
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, x_monitor_key="amk_not-a-real-key", auth=None, db=db)
    assert exc_info.value.status_code == 401


def test_legacy_static_monitor_key_still_works(db, admin, org):
    settings = get_settings()
    user = get_current_user(authorization=None, x_monitor_key=settings.monitor_api_key, auth=None, db=db)
    assert user.username == settings.admin_username


def test_using_key_updates_last_used_at(db, admin, org):
    created = _issue(db, admin, org)
    row = db.query(ApiKey).filter(ApiKey.id == created.id).one()
    assert row.last_used_at is None
    get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    db.refresh(row)
    assert row.last_used_at is not None


def test_admin_role_rejected_at_schema_level():
    with pytest.raises(ValidationError):
        ApiKeyCreateIn(name="too-privileged", role="admin")


def test_viewer_key_fails_editor_check(db, admin, org):
    created = _issue(db, admin, org, role="viewer")
    user = get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    check = require_role(Role.EDITOR)
    with pytest.raises(HTTPException) as exc_info:
        check(current_user=user)
    assert exc_info.value.status_code == 403


def test_editor_key_passes_editor_check(db, admin, org):
    created = _issue(db, admin, org, role="editor")
    user = get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    check = require_role(Role.EDITOR)
    assert check(current_user=user).username == user.username


def test_key_scoped_to_its_org_via_get_org_context(db, admin, org):
    """A resolved API-key user's org context is the key's own org, not the
    caller's X-Org-Id (keys never cross-org)."""
    from app.deps import get_org_context

    created = _issue(db, admin, org, role="editor")
    user = get_current_user(authorization=None, x_monitor_key=created.api_key, auth=None, db=db)
    ctx = get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert ctx.org_id == org.id
    assert ctx.role == OrgRole.EDITOR
