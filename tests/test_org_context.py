"""
Org context resolution tests (app.deps.get_org_context / require_org_role).

Covers:
  1. Sole active membership resolves with no X-Org-Id header.
  2. Zero memberships without a header is a 400 (no guessing).
  3. Multiple memberships without a header is a 400 (ambiguous).
  4. Explicit X-Org-Id resolves to that org's role when an active membership exists.
  5. Explicit X-Org-Id for an org the caller has no membership in is rejected (403)
     for a non-admin caller.
  6. A platform admin can cross-org access an explicit X-Org-Id they have no
     membership in, and it is audit-logged as "cross_org_access".
  7. A pending (not yet approved) membership does not count as active.
  8. A revoked membership does not count as active.
  9. require_org_role enforces the minimum org role (owner > editor > viewer).
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import get_org_context, require_org_role
from app.models import AuditLog, Base, Organization, OrgMembership, User
from app.security import OrgRole, hash_password


class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

_TABLES = [User.__table__, Organization.__table__, OrgMembership.__table__, AuditLog.__table__]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_user(db, username: str, role: str = "editor") -> User:
    u = User(username=username, password_hash=hash_password("P@ssw0rd123!"), role=role, is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_org(db, name: str, owner: User) -> Organization:
    o = Organization(name=name, slug=name.lower().replace(" ", "-"), owner_user_id=owner.id)
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def _membership(db, user: User, org: Organization, role: str = "owner", status: str = "active") -> OrgMembership:
    m = OrgMembership(user_id=user.id, org_id=org.id, role=role, status=status)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_sole_membership_resolves_without_header(db):
    user = _make_user(db, "alice")
    org = _make_org(db, "Acme", user)
    _membership(db, user, org, role="editor")

    ctx = get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert ctx.org_id == org.id
    assert ctx.role == OrgRole.EDITOR
    assert ctx.is_cross_org_admin is False


def test_zero_memberships_without_header_is_400(db):
    user = _make_user(db, "alice")
    with pytest.raises(HTTPException) as exc_info:
        get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert exc_info.value.status_code == 400


def test_multiple_memberships_without_header_is_400(db):
    user = _make_user(db, "alice")
    org_a = _make_org(db, "Acme", user)
    org_b = _make_org(db, "Globex", user)
    _membership(db, user, org_a)
    _membership(db, user, org_b)
    with pytest.raises(HTTPException) as exc_info:
        get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert exc_info.value.status_code == 400


def test_explicit_org_id_resolves_with_active_membership(db):
    user = _make_user(db, "alice")
    org_a = _make_org(db, "Acme", user)
    org_b = _make_org(db, "Globex", user)
    _membership(db, user, org_a, role="viewer")
    _membership(db, user, org_b, role="owner")

    ctx = get_org_context(request=FAKE_REQUEST, x_org_id=org_b.id, current_user=user, db=db)
    assert ctx.org_id == org_b.id
    assert ctx.role == OrgRole.OWNER


def test_explicit_org_id_without_membership_rejected_for_non_admin(db):
    user = _make_user(db, "alice", role="editor")
    other_owner = _make_user(db, "bob")
    other_org = _make_org(db, "Globex", other_owner)

    with pytest.raises(HTTPException) as exc_info:
        get_org_context(request=FAKE_REQUEST, x_org_id=other_org.id, current_user=user, db=db)
    assert exc_info.value.status_code == 403


def test_platform_admin_cross_org_access_is_audit_logged(db):
    admin = _make_user(db, "root", role="admin")
    other_owner = _make_user(db, "bob")
    other_org = _make_org(db, "Globex", other_owner)

    ctx = get_org_context(request=FAKE_REQUEST, x_org_id=other_org.id, current_user=admin, db=db)
    assert ctx.org_id == other_org.id
    assert ctx.is_cross_org_admin is True
    assert ctx.role == OrgRole.OWNER

    events = db.query(AuditLog).filter(AuditLog.event_type == "cross_org_access").all()
    assert len(events) == 1
    assert events[0].actor == "root"
    assert events[0].target == f"org/{other_org.id}"


def test_pending_membership_not_counted_as_active(db):
    user = _make_user(db, "alice")
    org = _make_org(db, "Acme", user)
    _membership(db, user, org, role="viewer", status="pending")

    with pytest.raises(HTTPException) as exc_info:
        get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert exc_info.value.status_code == 400


def test_revoked_membership_not_counted_as_active(db):
    user = _make_user(db, "alice")
    org = _make_org(db, "Acme", user)
    _membership(db, user, org, role="viewer", status="revoked")

    with pytest.raises(HTTPException) as exc_info:
        get_org_context(request=FAKE_REQUEST, x_org_id=None, current_user=user, db=db)
    assert exc_info.value.status_code == 400


def test_require_org_role_enforces_minimum():
    from app.deps import OrgContext

    check = require_org_role(OrgRole.EDITOR)
    viewer_ctx = OrgContext(org_id=1, role=OrgRole.VIEWER)
    with pytest.raises(HTTPException) as exc_info:
        check(ctx=viewer_ctx)
    assert exc_info.value.status_code == 403

    editor_ctx = OrgContext(org_id=1, role=OrgRole.EDITOR)
    assert check(ctx=editor_ctx) is editor_ctx

    owner_ctx = OrgContext(org_id=1, role=OrgRole.OWNER)
    assert check(ctx=owner_ctx) is owner_ctx
