"""
GET /api/inventory/traffic-trend — the read path that makes
``traffic_daily_summary`` load-bearing rather than write-only.

Raw TrafficEvent rows only survive RAW_RETENTION_DAYS (30); the scheduler's
rollup job folds anything older into traffic_daily_summary and deletes the
raw rows. So a window longer than that can only be answered by reading both
tables — these tests pin that behavior down.

Covers:
  1. Recent days are aggregated from raw traffic_events.
  2. Days past the raw-retention boundary come from traffic_daily_summary
     (proven by seeding ONLY a summary row there and still seeing it).
  3. A window spanning the boundary stitches both sources into one series.
  4. Error counts (status >= 400) are reported separately from total requests.
  5. The series is dense (zero-filled), so quiet days aren't silently dropped.
  6. Results are scoped to the caller's org.
"""

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.deps import OrgContext
from app.models import Alert, Base, DiscoveredEndpoint, KnownEndpoint, TrafficDailySummary, TrafficEvent
from app.routers.inventory import RAW_RETENTION_DAYS, traffic_trend
from app.security import OrgRole, utc_now

_TABLES = [
    TrafficEvent.__table__,
    TrafficDailySummary.__table__,
    DiscoveredEndpoint.__table__,
    KnownEndpoint.__table__,
    Alert.__table__,
]

_trend = traffic_trend.__wrapped__  # unwrap the slowapi rate-limit decorator


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


def _ctx(org_id: int = 1) -> OrgContext:
    return OrgContext(org_id=org_id, role=OrgRole.VIEWER)


def _add_event(db, *, org_id=1, days_ago=0, status_code=200):
    db.add(
        TrafficEvent(
            org_id=org_id,
            ts=utc_now() - timedelta(days=days_ago),
            method="GET",
            path="/api/items",
            status_code=status_code,
            latency_ms=5.0,
        )
    )


def _add_summary(db, *, org_id=1, days_ago=40, requests=100, errors=5):
    day = (utc_now() - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)
    db.add(
        TrafficDailySummary(
            org_id=org_id,
            day=day,
            method="GET",
            path_normalized="/api/items",
            request_count=requests,
            error_count=errors,
            avg_response_time_ms=12.0,
        )
    )


def test_recent_days_come_from_raw_events(db):
    _add_event(db, days_ago=0)
    _add_event(db, days_ago=0)
    _add_event(db, days_ago=1)
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(), db=db, days=7)

    by_day = {p.day: p.requests for p in series}
    today = utc_now().date().isoformat()
    yesterday = (utc_now() - timedelta(days=1)).date().isoformat()
    assert by_day[today] == 2
    assert by_day[yesterday] == 1


def test_old_days_come_from_summary_table(db):
    # Only a summary row exists for this day — no raw events at all, exactly
    # as it would be after the rollup job pruned them. If the endpoint only
    # read traffic_events this would come back zero.
    _add_summary(db, days_ago=40, requests=250, errors=12)
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(), db=db, days=60)

    target = (utc_now() - timedelta(days=40)).date().isoformat()
    point = next(p for p in series if p.day == target)
    assert point.requests == 250
    assert point.errors == 12


def test_window_spanning_boundary_stitches_both_sources(db):
    _add_event(db, days_ago=1)  # recent -> raw
    _add_summary(db, days_ago=45, requests=99, errors=0)  # old -> summary
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(), db=db, days=60)

    by_day = {p.day: p.requests for p in series}
    assert by_day[(utc_now() - timedelta(days=1)).date().isoformat()] == 1
    assert by_day[(utc_now() - timedelta(days=45)).date().isoformat()] == 99


def test_error_counts_reported_separately(db):
    _add_event(db, days_ago=0, status_code=200)
    _add_event(db, days_ago=0, status_code=500)
    _add_event(db, days_ago=0, status_code=404)
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(), db=db, days=2)

    today = next(p for p in series if p.day == utc_now().date().isoformat())
    assert today.requests == 3
    assert today.errors == 2


def test_series_is_dense_and_zero_filled(db):
    _add_event(db, days_ago=0)
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(), db=db, days=7)

    assert len(series) == 7
    assert sum(p.requests for p in series) == 1
    assert all(p.requests == 0 for p in series if p.day != utc_now().date().isoformat())


def test_scoped_to_caller_org(db):
    _add_event(db, org_id=1, days_ago=0)
    _add_event(db, org_id=2, days_ago=0)
    _add_summary(db, org_id=2, days_ago=40, requests=500)
    db.commit()

    series = _trend(request=_FakeRequest(), ctx=_ctx(org_id=1), db=db, days=60)

    assert sum(p.requests for p in series) == 1  # org 2's raw event and summary excluded


def test_raw_retention_constant_matches_scheduler_rollup():
    """The boundary this endpoint splits on must match the rollup job's
    keep_days, or the two ranges would overlap (double-counting) or leave a
    gap (silently missing days)."""
    import inspect

    from app.jobs import scheduler

    source = inspect.getsource(scheduler._traffic_rollup.__wrapped__)
    assert f"keep_days={RAW_RETENTION_DAYS}" in source
