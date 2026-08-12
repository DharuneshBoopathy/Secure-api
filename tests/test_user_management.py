"""
Platform user-management endpoint tests (app/routers/auth.py).

The admin tier used to be self-governing: any admin could demote or
deactivate any other admin, so granting someone the admin role handed them
the power to lock you out of your own deployment, and whoever moved first
won. These tests pin the hierarchy that replaced it.

Covers:
  1. A plain admin cannot demote, deactivate, or delete another admin.
  2. A plain admin cannot grant the admin role (on update or on create).
  3. A super admin can do all of the above.
  4. Nobody can demote, deactivate, or delete a super admin — including the
     super admin themselves.
  5. A plain admin retains full control over editor/viewer accounts.
  6. PATCH is_active=false on your own account is refused (the DELETE route
     always refused it; PATCH used to be an open back door).
  7. Deactivating through PATCH revokes refresh tokens, as DELETE does.
  8. Reactivating through PATCH works (the UI's only way back).
  9. ensure_default_admin restores a demoted / deactivated / locked-out
     bootstrap account on the next boot.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base, Organization, OrgMembership, RefreshToken, User
from app.routers.auth import admin_create_user as _create_wrapped
from app.routers.auth import delete_user as _delete_user
from app.routers.auth import ensure_default_admin
from app.routers.auth import update_user as _update_wrapped
from app.schemas import AdminCreateUserIn, UserUpdateIn
from app.security import Role, hash_password, utc_now

_admin_create_user = _create_wrapped.__wrapped__
_update_user = _update_wrapped.__wrapped__


class _FakeClient:
    host = "127.0.0.1"


class _FakeHeaders:
    def get(self, key, default=None):
        return default


class _FakeRequest:
    client = _FakeClient()
    headers = _FakeHeaders()


FAKE_REQUEST = _FakeRequest()

_TABLES = [
    User.__table__,
    Organization.__table__,
    OrgMembership.__table__,
    RefreshToken.__table__,
    AuditLog.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_user(db, username: str, role: str = "viewer", is_active: bool = True) -> User:
    u = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("P@ssw0rd123!"),
        role=role,
        is_active=is_active,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _patch(db, actor: User, target: User, **fields):
    return _update_user(
        request=FAKE_REQUEST,
        user_id=target.id,
        body=UserUpdateIn(**fields),
        admin=actor,
        db=db,
    )


# ---------------------------------------------------------------------------
# 1-2. A plain admin cannot touch another admin, nor mint one
# ---------------------------------------------------------------------------

def test_admin_cannot_demote_another_admin(db):
    actor = _make_user(db, "alice", role="admin")
    peer = _make_user(db, "bob", role="admin")

    with pytest.raises(HTTPException) as exc:
        _patch(db, actor, peer, role="viewer")

    assert exc.value.status_code == 403
    db.refresh(peer)
    assert peer.role == "admin"


def test_admin_cannot_deactivate_another_admin_via_patch(db):
    actor = _make_user(db, "alice", role="admin")
    peer = _make_user(db, "bob", role="admin")

    with pytest.raises(HTTPException) as exc:
        _patch(db, actor, peer, is_active=False)

    assert exc.value.status_code == 403
    db.refresh(peer)
    assert peer.is_active is True


def test_admin_cannot_deactivate_another_admin_via_delete(db):
    actor = _make_user(db, "alice", role="admin")
    peer = _make_user(db, "bob", role="admin")

    with pytest.raises(HTTPException) as exc:
        _delete_user(request=FAKE_REQUEST, user_id=peer.id, admin=actor, db=db)

    assert exc.value.status_code == 403
    db.refresh(peer)
    assert peer.is_active is True


def test_admin_cannot_grant_the_admin_role(db):
    actor = _make_user(db, "alice", role="admin")
    target = _make_user(db, "bob", role="viewer")

    with pytest.raises(HTTPException) as exc:
        _patch(db, actor, target, role="admin")

    assert exc.value.status_code == 403
    db.refresh(target)
    assert target.role == "viewer"


def test_admin_cannot_create_an_admin(db):
    actor = _make_user(db, "alice", role="admin")

    with pytest.raises(HTTPException) as exc:
        _admin_create_user(
            request=FAKE_REQUEST,
            body=AdminCreateUserIn(
                username="mallory",
                password="P@ssw0rd123!",
                email="mallory@example.com",
                role="admin",
            ),
            current_user=actor,
            db=db,
        )

    assert exc.value.status_code == 403
    assert db.query(User).filter(User.username == "mallory").one_or_none() is None


# ---------------------------------------------------------------------------
# 3. The super admin can
# ---------------------------------------------------------------------------

def test_super_admin_can_demote_and_deactivate_an_admin(db):
    root = _make_user(db, "dharunesh", role="super_admin")
    peer = _make_user(db, "bob", role="admin")

    _patch(db, root, peer, role="viewer")
    db.refresh(peer)
    assert peer.role == "viewer"

    _delete_user(request=FAKE_REQUEST, user_id=peer.id, admin=root, db=db)
    db.refresh(peer)
    assert peer.is_active is False


def test_super_admin_can_grant_the_admin_role(db):
    root = _make_user(db, "dharunesh", role="super_admin")
    target = _make_user(db, "bob", role="viewer")

    out = _patch(db, root, target, role="admin")

    assert out.role == "admin"


# ---------------------------------------------------------------------------
# 4. The super admin is untouchable, by anyone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("actor_role", ["admin", "super_admin"])
def test_super_admin_cannot_be_demoted(db, actor_role):
    actor = _make_user(db, "actor", role=actor_role)
    root = _make_user(db, "dharunesh", role="super_admin")

    with pytest.raises(HTTPException) as exc:
        _patch(db, actor, root, role="viewer")

    assert exc.value.status_code == 403
    db.refresh(root)
    assert root.role == "super_admin"


@pytest.mark.parametrize("actor_role", ["admin", "super_admin"])
def test_super_admin_cannot_be_deactivated(db, actor_role):
    actor = _make_user(db, "actor", role=actor_role)
    root = _make_user(db, "dharunesh", role="super_admin")

    with pytest.raises(HTTPException) as exc:
        _delete_user(request=FAKE_REQUEST, user_id=root.id, admin=actor, db=db)

    assert exc.value.status_code == 403
    db.refresh(root)
    assert root.is_active is True


def test_super_admin_cannot_demote_themselves(db):
    """Self-inflicted lockout is the same outage as a hostile one, and there
    is no account above this one to undo it."""
    root = _make_user(db, "dharunesh", role="super_admin")

    with pytest.raises(HTTPException) as exc:
        _patch(db, root, root, role="admin")

    assert exc.value.status_code == 403
    db.refresh(root)
    assert root.role == "super_admin"


# ---------------------------------------------------------------------------
# 5. Ordinary accounts are still fully manageable by a plain admin
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_role", ["viewer", "editor"])
def test_admin_retains_control_over_non_admins(db, target_role):
    actor = _make_user(db, "alice", role="admin")
    target = _make_user(db, "bob", role=target_role)

    out = _patch(db, actor, target, role="editor" if target_role == "viewer" else "viewer")
    assert out.role == ("editor" if target_role == "viewer" else "viewer")

    _delete_user(request=FAKE_REQUEST, user_id=target.id, admin=actor, db=db)
    db.refresh(target)
    assert target.is_active is False


# ---------------------------------------------------------------------------
# 6-8. is_active handling through PATCH
# ---------------------------------------------------------------------------

def test_patch_cannot_deactivate_your_own_account(db):
    """DELETE has always refused this; PATCH accepting it made that guard
    decorative."""
    actor = _make_user(db, "alice", role="admin")

    with pytest.raises(HTTPException) as exc:
        _patch(db, actor, actor, is_active=False)

    assert exc.value.status_code == 400
    db.refresh(actor)
    assert actor.is_active is True


def test_patch_deactivation_revokes_refresh_tokens(db):
    actor = _make_user(db, "alice", role="admin")
    target = _make_user(db, "bob", role="viewer")
    db.add(
        RefreshToken(
            user_id=target.id,
            token="a" * 64,
            expires_at=utc_now(),
            revoked=False,
        )
    )
    db.commit()

    _patch(db, actor, target, is_active=False)

    remaining = (
        db.query(RefreshToken)
        .filter(RefreshToken.user_id == target.id, RefreshToken.revoked.is_(False))
        .count()
    )
    assert remaining == 0


def test_patch_can_reactivate_a_deactivated_user(db):
    actor = _make_user(db, "alice", role="admin")
    target = _make_user(db, "bob", role="viewer", is_active=False)

    out = _patch(db, actor, target, is_active=True)

    assert out.is_active is True


# ---------------------------------------------------------------------------
# 9. Boot-time repair — the deployment's lockout recovery path
# ---------------------------------------------------------------------------

def test_ensure_default_admin_creates_a_super_admin(db):
    ensure_default_admin(db)

    from app.config import get_settings

    user = db.query(User).filter(User.username == get_settings().admin_username).one()
    assert user.role == Role.SUPER_ADMIN.value
    assert user.is_active is True


def test_ensure_default_admin_repairs_a_demoted_and_disabled_account(db):
    from app.config import get_settings

    username = get_settings().admin_username
    hostile = _make_user(db, username, role="viewer", is_active=False)
    hostile.failed_login_count = 5
    hostile.locked_until = utc_now()
    db.commit()

    ensure_default_admin(db)

    db.refresh(hostile)
    assert hostile.role == Role.SUPER_ADMIN.value
    assert hostile.is_active is True
    assert hostile.failed_login_count == 0
    assert hostile.locked_until is None
