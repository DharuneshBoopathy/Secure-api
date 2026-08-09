"""
End-to-end tenant isolation tests: ingesting traffic into one organization
must never be visible through another organization's read routes.

Covers:
  1. TrafficEvent rows are stamped with the ingesting org's id.
  2. DiscoveredEndpoint/ShadowEndpoint bookkeeping is scoped per org — the
     same undocumented path hit by two different orgs produces two separate
     rows, not one shared/double-counted row.
  3. inventory.list_discovered only returns the caller's org's rows.
  4. shadow.list_shadow only returns the caller's org's rows.
  5. alerts.list_alerts only returns the caller's org's rows.
  6. A viewer in org A cannot see org B's data even via the same endpoint,
     when both orgs independently trigger the same alert-worthy condition.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import OrgContext
from app.models import (
    Alert,
    AuditLog,
    Base,
    DiscoveredEndpoint,
    KnownEndpoint,
    Organization,
    OrgMembership,
    ShadowEndpoint,
    TrafficEvent,
    User,
)
from app.routers.alerts import list_alerts as _list_alerts
from app.routers.inventory import list_discovered as _list_discovered_wrapped
from app.routers.shadow import list_shadow as _list_shadow
from app.security import OrgRole, hash_password
from app.services.traffic_processor import process_single_event

# list_discovered carries slowapi's rate-limit decorator; call the undecorated
# function directly so these tests don't consume a per-IP quota.
_list_discovered = _list_discovered_wrapped.__wrapped__

_TABLES = [
    User.__table__, Organization.__table__, OrgMembership.__table__, AuditLog.__table__,
    TrafficEvent.__table__, DiscoveredEndpoint.__table__, ShadowEndpoint.__table__,
    KnownEndpoint.__table__, Alert.__table__,
]


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
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def two_orgs(db):
    owner_a = User(username="owner_a", password_hash=hash_password("P@ssw0rd123!"), role="editor", is_active=True)
    owner_b = User(username="owner_b", password_hash=hash_password("P@ssw0rd123!"), role="editor", is_active=True)
    db.add_all([owner_a, owner_b])
    db.commit()
    db.refresh(owner_a)
    db.refresh(owner_b)

    org_a = Organization(name="Org A", slug="org-a", owner_user_id=owner_a.id)
    org_b = Organization(name="Org B", slug="org-b", owner_user_id=owner_b.id)
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)
    return org_a, org_b


def _ingest(db, org_id: int, path: str = "/api/undocumented"):
    return process_single_event(
        db,
        org_id=org_id,
        method="GET",
        path=path,
        status_code=200,
        latency_ms=5.0,
        client_ip="10.0.0.1",
        user_agent="test",
        auth_present=False,
        body_bytes=0,
        request_size_bytes=0,
        response_size_bytes=0,
        content_type=None,
        x_forwarded_for=None,
        referer=None,
        monitor_key=None,
        session_id=None,
        gateway="test",
        raw_ref=None,
        model=None,
    )


def test_traffic_event_stamped_with_ingesting_org(db, two_orgs):
    org_a, org_b = two_orgs
    ev = _ingest(db, org_a.id)
    assert ev.org_id == org_a.id


def test_discovered_and_shadow_rows_are_per_org_not_shared(db, two_orgs):
    org_a, org_b = two_orgs
    _ingest(db, org_a.id, "/api/secret")
    _ingest(db, org_b.id, "/api/secret")

    discovered = db.query(DiscoveredEndpoint).filter(DiscoveredEndpoint.path_normalized == "/api/secret").all()
    assert len(discovered) == 2
    assert {d.org_id for d in discovered} == {org_a.id, org_b.id}
    assert all(d.hit_count == 1 for d in discovered)  # not double-counted into one row

    shadow = db.query(ShadowEndpoint).filter(ShadowEndpoint.path_normalized == "/api/secret").all()
    assert len(shadow) == 2
    assert {s.org_id for s in shadow} == {org_a.id, org_b.id}


def test_list_discovered_scoped_to_caller_org(db, two_orgs):
    org_a, org_b = two_orgs
    _ingest(db, org_a.id, "/api/onlyina")
    _ingest(db, org_b.id, "/api/onlyinb")

    ctx_a = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    ctx_b = OrgContext(org_id=org_b.id, role=OrgRole.VIEWER)

    rows_a = _list_discovered(request=_FakeRequest(), ctx=ctx_a, db=db)
    rows_b = _list_discovered(request=_FakeRequest(), ctx=ctx_b, db=db)

    assert [r.path_normalized for r in rows_a] == ["/api/onlyina"]
    assert [r.path_normalized for r in rows_b] == ["/api/onlyinb"]


def test_list_shadow_scoped_to_caller_org(db, two_orgs):
    org_a, org_b = two_orgs
    _ingest(db, org_a.id, "/api/shadow-a")
    _ingest(db, org_b.id, "/api/shadow-b")

    ctx_a = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    result_a = _list_shadow(ctx=ctx_a, db=db, page=1, page_size=25, risk_level=None, sort_by="risk_score")
    paths_a = [item.path_normalized for item in result_a["items"]]
    assert paths_a == ["/api/shadow-a"]


def test_list_alerts_scoped_to_caller_org(db, two_orgs):
    org_a, org_b = two_orgs
    # Undocumented-endpoint alerts fire on first hit for each org independently.
    _ingest(db, org_a.id, "/api/alert-path")
    _ingest(db, org_b.id, "/api/alert-path")

    ctx_a = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    ctx_b = OrgContext(org_id=org_b.id, role=OrgRole.VIEWER)

    alerts_a = _list_alerts(ctx=ctx_a, db=db, limit=100, open_only=True)
    alerts_b = _list_alerts(ctx=ctx_b, db=db, limit=100, open_only=True)

    assert len(alerts_a) == 1
    assert len(alerts_b) == 1
    # Both orgs got their own alert row — not one shared/deduplicated-across-orgs row.
    all_alert_ids = {a.id for a in alerts_a} | {a.id for a in alerts_b}
    assert len(all_alert_ids) == 2
