"""
Organization membership endpoint tests (app/routers/orgs.py).

Covers:
  1. Creating an org makes the creator its active owner.
  2. list_my_orgs only returns active memberships, with the caller's role.
  3. A join request creates a pending membership granting no access.
  4. A non-owner cannot approve/reject/list members (403).
  5. An owner can approve a pending request -> active, default role viewer.
  6. An owner can reject a pending request -> revoked.
  7. Re-requesting after rejection is allowed (revoked -> pending again).
  8. Duplicate join request while already pending/active is rejected (409).
  9. An owner can change an active member's role.
  10. An owner cannot remove the org owner directly (must transfer first).
  11. An owner can remove a non-owner active member (-> revoked).
  12. Ownership transfer demotes the prior owner to editor and updates Organization.owner_user_id.
  13. Renaming an org requires owner role.
  14. A platform admin can manage any org's membership without an OrgMembership row.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base, Organization, OrgMembership, User
from app.routers.orgs import approve_member as _approve_wrapped
from app.routers.orgs import create_org as _create_wrapped
from app.routers.orgs import list_members as _list_members
from app.routers.orgs import list_my_orgs as _list_orgs
from app.routers.orgs import reject_member as _reject_wrapped
from app.routers.orgs import remove_member as _remove_wrapped
from app.routers.orgs import rename_org as _rename_wrapped
from app.routers.orgs import request_to_join as _request_wrapped
from app.routers.orgs import transfer_ownership as _transfer_wrapped
from app.routers.orgs import update_member as _update_wrapped
from app.schemas import OrgCreateIn, OrgMembershipRoleIn, OrgRenameIn, OrgTransferOwnershipIn
from app.security import hash_password

_create_org = _create_wrapped.__wrapped__
_request_to_join = _request_wrapped.__wrapped__
_approve_member = _approve_wrapped
_reject_member = _reject_wrapped
_remove_member = _remove_wrapped
_update_member = _update_wrapped
_rename_org = _rename_wrapped
_transfer_ownership = _transfer_wrapped
_list_my_orgs = _list_orgs
_list_org_members = _list_members


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


def test_create_org_makes_creator_owner(db):
    alice = _make_user(db, "alice")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme Inc"), current_user=alice, db=db)
    assert org.my_role == "owner"
    assert org.owner_user_id == alice.id
    assert org.slug == "acme-inc"


def test_list_my_orgs_returns_only_active_memberships_with_role(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)

    assert _list_my_orgs(current_user=alice, db=db)[0].my_role == "owner"
    assert _list_my_orgs(current_user=bob, db=db) == []


def test_join_request_creates_pending_membership(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)

    result = _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    assert result.status == "pending"
    assert result.role == "viewer"
    # Pending membership means bob is NOT in alice's active-member list yet.
    assert _list_my_orgs(current_user=bob, db=db) == []


def test_non_owner_cannot_manage_members(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    carol = _make_user(db, "carol")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)

    with pytest.raises(HTTPException) as exc_info:
        _list_org_members(org_id=org.id, status_filter=None, current_user=carol, db=db)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        _approve_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=carol, db=db)
    assert exc_info.value.status_code == 403


def test_owner_can_approve_pending_request(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)

    approved = _approve_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)
    assert approved.status == "active"
    assert approved.role == "viewer"
    assert any(o.id == org.id for o in _list_my_orgs(current_user=bob, db=db))


def test_owner_can_reject_pending_request(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)

    result = _reject_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)
    assert result == {"rejected": True}
    m = db.query(OrgMembership).filter(OrgMembership.user_id == bob.id, OrgMembership.org_id == org.id).one()
    assert m.status == "revoked"


def test_can_re_request_after_rejection(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    _reject_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)

    result = _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    assert result.status == "pending"


def test_duplicate_join_request_rejected(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)

    with pytest.raises(HTTPException) as exc_info:
        _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    assert exc_info.value.status_code == 409


def test_owner_can_change_member_role(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    _approve_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)

    updated = _update_member(
        request=FAKE_REQUEST, org_id=org.id, user_id=bob.id,
        body=OrgMembershipRoleIn(role="editor"), current_user=alice, db=db,
    )
    assert updated.role == "editor"


def test_cannot_remove_org_owner_directly(db):
    alice = _make_user(db, "alice")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)

    with pytest.raises(HTTPException) as exc_info:
        _remove_member(request=FAKE_REQUEST, org_id=org.id, user_id=alice.id, current_user=alice, db=db)
    assert exc_info.value.status_code == 400


def test_owner_can_remove_non_owner_member(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    _approve_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)

    _remove_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)
    m = db.query(OrgMembership).filter(OrgMembership.user_id == bob.id, OrgMembership.org_id == org.id).one()
    assert m.status == "revoked"


def test_transfer_ownership_demotes_prior_owner(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)
    _request_to_join(request=FAKE_REQUEST, org_id=org.id, current_user=bob, db=db)
    _approve_member(request=FAKE_REQUEST, org_id=org.id, user_id=bob.id, current_user=alice, db=db)

    result = _transfer_ownership(
        request=FAKE_REQUEST, org_id=org.id,
        body=OrgTransferOwnershipIn(new_owner_user_id=bob.id), current_user=alice, db=db,
    )
    assert result.owner_user_id == bob.id

    alice_membership = db.query(OrgMembership).filter(OrgMembership.user_id == alice.id, OrgMembership.org_id == org.id).one()
    bob_membership = db.query(OrgMembership).filter(OrgMembership.user_id == bob.id, OrgMembership.org_id == org.id).one()
    assert alice_membership.role == "editor"
    assert bob_membership.role == "owner"


def test_rename_requires_owner_role(db):
    alice = _make_user(db, "alice")
    bob = _make_user(db, "bob")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)

    with pytest.raises(HTTPException) as exc_info:
        _rename_org(request=FAKE_REQUEST, org_id=org.id, body=OrgRenameIn(name="New Name"), current_user=bob, db=db)
    assert exc_info.value.status_code == 403

    renamed = _rename_org(request=FAKE_REQUEST, org_id=org.id, body=OrgRenameIn(name="New Name"), current_user=alice, db=db)
    assert renamed.name == "New Name"


def test_platform_admin_can_manage_any_org_without_membership(db):
    alice = _make_user(db, "alice")
    admin = _make_user(db, "root", role="admin")
    org = _create_org(request=FAKE_REQUEST, body=OrgCreateIn(name="Acme"), current_user=alice, db=db)

    members = _list_org_members(org_id=org.id, status_filter=None, current_user=admin, db=db)
    assert len(members) == 1
    assert members[0].username == "alice"
