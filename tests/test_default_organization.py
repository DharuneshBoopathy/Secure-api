"""
Default-organization bootstrap tests (app.routers.auth.ensure_default_organization).

Covers:
  1. Fresh install (admin exists, no org yet) creates "Default Organization"
     owned by the admin, with an active owner membership.
  2. No-op when a "default" org already exists.
  3. No-op (does not crash) when no admin user exists yet.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import Base, Organization, OrgMembership, User
from app.routers.auth import ensure_default_organization
from app.security import hash_password

_TABLES = [User.__table__, Organization.__table__, OrgMembership.__table__]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_admin(db) -> User:
    u = User(
        username=get_settings().admin_username,
        password_hash=hash_password("P@ssw0rd123!"),
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_creates_default_org_owned_by_admin(db):
    admin = _make_admin(db)
    ensure_default_organization(db)

    org = db.query(Organization).filter(Organization.slug == "default").one()
    assert org.owner_user_id == admin.id

    membership = db.query(OrgMembership).filter(OrgMembership.org_id == org.id, OrgMembership.user_id == admin.id).one()
    assert membership.role == "owner"
    assert membership.status == "active"


def test_noop_when_default_org_already_exists(db):
    _make_admin(db)
    ensure_default_organization(db)
    ensure_default_organization(db)  # second call must not duplicate

    assert db.query(Organization).filter(Organization.slug == "default").count() == 1
    assert db.query(OrgMembership).count() == 1


def test_noop_when_no_admin_exists_yet(db):
    ensure_default_organization(db)  # must not raise
    assert db.query(Organization).count() == 0
