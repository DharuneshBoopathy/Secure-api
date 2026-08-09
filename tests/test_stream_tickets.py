"""SSE authentication via short-lived stream tickets.

EventSource cannot send headers, so the credential for a stream has to travel
in the URL — and therefore into every access log along the path. Previously
that was the caller's full access token. These tests pin the properties that
make a ticket a materially smaller thing to leak:

  1. it is rejected by ordinary API routes (distinct `type` claim),
  2. it expires in ~a minute,
  3. it carries its own organization, so the streams work for users who
     belong to more than one org (EventSource can't send X-Org-Id either),
  4. membership is re-checked at connect time, so revoking access takes
     effect before the ticket's own expiry.
"""

import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import get_current_user, get_stream_org_context
from app.models import Base, Organization, OrgMembership, User
from app.security import (
    STREAM_TICKET_TTL_SECONDS,
    OrgRole,
    create_access_token,
    create_stream_ticket,
    decode_token,
    hash_password,
)

_TABLES = [User.__table__, Organization.__table__, OrgMembership.__table__]


class _FakeRequest:
    class client:
        host = "127.0.0.1"

    class headers:
        @staticmethod
        def get(key, default=None):
            return default


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=_TABLES)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def viewer_in_two_orgs(db):
    user = User(username="viewer", password_hash=hash_password("P@ssw0rd123!"), role="viewer", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    orgs = []
    for name in ("Acme", "Globex"):
        org = Organization(name=name, slug=name.lower(), owner_user_id=user.id)
        db.add(org)
        db.commit()
        db.refresh(org)
        db.add(OrgMembership(user_id=user.id, org_id=org.id, role="viewer", status="active"))
        orgs.append(org)
    db.commit()
    return user, orgs


def _ctx(db, ticket):
    return get_stream_org_context(
        request=_FakeRequest(), ticket=ticket, authorization=None, x_monitor_key=None, x_org_id=None, db=db
    )


# ---------------------------------------------------------------------------
# the ticket is a weaker credential than the token it replaced
# ---------------------------------------------------------------------------

def test_ticket_is_short_lived():
    _, expires_in = create_stream_ticket("viewer", 1)
    assert expires_in == STREAM_TICKET_TTL_SECONDS
    assert expires_in <= 120, "a ticket that outlives its own page load is not bounded exposure"


def test_ticket_is_typed_distinctly_from_an_access_token():
    ticket, _ = create_stream_ticket("viewer", 1)
    assert decode_token(ticket)["type"] == "stream"
    access, _ = create_access_token("viewer")
    assert decode_token(access)["type"] == "access"


def test_ticket_is_rejected_by_ordinary_api_auth(db, viewer_in_two_orgs):
    """The whole point: a ticket recovered from a log cannot call the REST API."""
    ticket, _ = create_stream_ticket("viewer", 1)
    with pytest.raises(HTTPException) as exc:
        get_current_user(authorization=f"Bearer {ticket}", x_monitor_key=None, auth=None, db=db)
    assert exc.value.status_code == 401


def test_access_token_is_rejected_as_a_stream_ticket(db, viewer_in_two_orgs):
    """And the reverse — the query parameter accepts tickets only, so the old
    'paste the access token in the URL' path is genuinely closed."""
    access, _ = create_access_token("viewer")
    with pytest.raises(HTTPException) as exc:
        _ctx(db, access)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# org binding
# ---------------------------------------------------------------------------

def test_ticket_carries_its_org_so_multi_org_users_can_stream(db, viewer_in_two_orgs):
    """Without the org claim this 400s: EventSource can't send X-Org-Id, so
    resolution would fall back to 'the caller's only membership' and this user
    has two."""
    _, orgs = viewer_in_two_orgs
    for org in orgs:
        ticket, _ = create_stream_ticket("viewer", org.id)
        ctx = _ctx(db, ticket)
        assert ctx.org_id == org.id
        assert ctx.role == OrgRole.VIEWER


def test_ticket_for_an_org_the_user_does_not_belong_to_is_rejected(db, viewer_in_two_orgs):
    ticket, _ = create_stream_ticket("viewer", 9999)
    with pytest.raises(HTTPException) as exc:
        _ctx(db, ticket)
    assert exc.value.status_code == 401


def test_membership_is_rechecked_at_connect_time(db, viewer_in_two_orgs):
    """A ticket minted while the user was a member must stop working the
    moment membership is revoked — not merely when the ticket expires."""
    user, orgs = viewer_in_two_orgs
    ticket, _ = create_stream_ticket("viewer", orgs[0].id)
    assert _ctx(db, ticket).org_id == orgs[0].id

    db.query(OrgMembership).filter(
        OrgMembership.user_id == user.id, OrgMembership.org_id == orgs[0].id
    ).update({"status": "revoked"})
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _ctx(db, ticket)
    assert exc.value.status_code == 401


def test_deactivated_user_cannot_use_an_outstanding_ticket(db, viewer_in_two_orgs):
    user, orgs = viewer_in_two_orgs
    ticket, _ = create_stream_ticket("viewer", orgs[0].id)
    user.is_active = False
    db.commit()
    with pytest.raises(HTTPException):
        _ctx(db, ticket)


# ---------------------------------------------------------------------------
# malformed input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b.c", None])
def test_malformed_or_missing_ticket_is_401_not_500(db, viewer_in_two_orgs, bad):
    with pytest.raises(HTTPException) as exc:
        _ctx(db, bad)
    assert exc.value.status_code == 401


def test_expired_ticket_is_rejected(db, viewer_in_two_orgs, monkeypatch):
    import app.security as security_module

    _, orgs = viewer_in_two_orgs
    monkeypatch.setattr(security_module, "STREAM_TICKET_TTL_SECONDS", 1)
    ticket, _ = create_stream_ticket("viewer", orgs[0].id)
    time.sleep(1.2)
    with pytest.raises(HTTPException) as exc:
        _ctx(db, ticket)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# header auth still works for non-browser clients
# ---------------------------------------------------------------------------

def test_header_auth_still_works_and_needs_no_url_credential(db, viewer_in_two_orgs):
    """curl / integration clients can send Authorization normally, keeping the
    credential out of the URL entirely."""
    _, orgs = viewer_in_two_orgs
    access, _ = create_access_token("viewer")
    ctx = get_stream_org_context(
        request=_FakeRequest(),
        ticket=None,
        authorization=f"Bearer {access}",
        x_monitor_key=None,
        x_org_id=orgs[1].id,
        db=db,
    )
    assert ctx.org_id == orgs[1].id
