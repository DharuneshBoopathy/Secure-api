"""
GET /api/alerts/stream (Phase 7: real-time alert toasts) — the SSE feed
app/routers/alerts.py::stream_alerts pushes newly-created alerts over,
mirroring app/routers/traffic.py::stream_traffic's polling-generator shape.

Covers:
  1. The stream starts at the org's current max alert id, not 0 — an alert
     that already existed before the client connected must NOT be replayed
     (unlike the traffic stream, which intentionally shows history).
  2. An alert created after the stream starts IS yielded, with the same
     fields GET /alerts returns (event_id, explanation, feedback, etc.).
  3. Alerts from another org are never yielded (tenant isolation).
"""

import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.deps import OrgContext
from app.models import Alert, Base, Organization, OrgMembership, User
from app.routers.alerts import stream_alerts
from app.security import OrgRole, hash_password

_TABLES = [User.__table__, Organization.__table__, OrgMembership.__table__, Alert.__table__]


class _FakeRequest:
    class client:
        host = "127.0.0.1"

    class headers:
        @staticmethod
        def get(key, default=None):
            return default


@pytest.fixture()
def db():
    # StaticPool (not just check_same_thread=False): stream_alerts's query
    # runs via run_in_threadpool, i.e. on a different thread than this
    # fixture. Without a shared pool, that thread would open a *new*,
    # separate `:memory:` database with no tables at all.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
    org_a = Organization(name="Org A", slug="org-a", owner_user_id=owner_a.id)
    org_b = Organization(name="Org B", slug="org-b", owner_user_id=owner_b.id)
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)
    return org_a, org_b


def _next_payload(body_iterator, timeout: float = 5.0) -> dict:
    async def _pull():
        chunk = await asyncio.wait_for(body_iterator.__anext__(), timeout=timeout)
        line = chunk.split("data: ", 1)[1].strip()
        return json.loads(line)

    return asyncio.run(_pull())


def test_stream_does_not_replay_pre_existing_alerts(db, two_orgs):
    org_a, _ = two_orgs
    db.add(Alert(org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="old", detail="old"))
    db.commit()

    ctx = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    response = stream_alerts.__wrapped__(request=_FakeRequest(), db=db, ctx=ctx)

    new_alert = Alert(org_id=org_a.id, alert_type="undocumented_api", severity="high", title="new", detail="new")
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)

    payload = _next_payload(response.body_iterator)
    assert payload["title"] == "new"
    assert payload["id"] == new_alert.id


def test_stream_only_yields_callers_org(db, two_orgs):
    org_a, org_b = two_orgs
    ctx_a = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    response = stream_alerts.__wrapped__(request=_FakeRequest(), db=db, ctx=ctx_a)

    db.add(Alert(org_id=org_b.id, alert_type="traffic_anomaly", severity="medium", title="org-b-alert", detail="x"))
    db.add(Alert(org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="org-a-alert", detail="x"))
    db.commit()

    payload = _next_payload(response.body_iterator)
    assert payload["title"] == "org-a-alert"


def test_stream_payload_matches_alert_out_shape(db, two_orgs):
    org_a, _ = two_orgs
    ctx = OrgContext(org_id=org_a.id, role=OrgRole.VIEWER)
    response = stream_alerts.__wrapped__(request=_FakeRequest(), db=db, ctx=ctx)

    db.add(Alert(
        org_id=org_a.id, alert_type="traffic_anomaly", severity="medium", title="scored", detail="x",
        event_id=42, explanation=[{"feature": "query_entropy", "value": 5.0, "baseline_mean": 1.0, "z_score": 4.0}],
    ))
    db.commit()

    payload = _next_payload(response.body_iterator)
    assert payload["event_id"] == 42
    assert payload["explanation"][0]["feature"] == "query_entropy"
    assert payload["feedback"] is None
    assert payload["acknowledged"] is False
