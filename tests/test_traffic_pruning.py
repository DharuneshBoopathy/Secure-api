"""
Validates Task 3: Automated stale traffic pruning.

Tests confirm that:
  1. prune_stale_traffic() deletes rows older than zombie_window_days.
  2. Recent rows (within the window) are preserved.
  3. Chunked deletion works correctly when more rows exist than the chunk size.
  4. Zero rows deleted when there is nothing stale.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.jobs.scheduler import prune_stale_traffic
from app.models import Base, TrafficEvent


# ---------------------------------------------------------------------------
# Shared fixture: in-memory SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """In-memory SQLite session.  Only creates the traffic_events table to avoid
    MySQL-specific column types (LONGTEXT) present in other models."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[TrafficEvent.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_event(ts: datetime) -> TrafficEvent:
    return TrafficEvent(
        ts=ts,
        method="GET",
        path="/test",
        status_code=200,
        latency_ms=5.0,
        body_bytes=0,
    )


# Patch get_settings so zombie_window_days = 30 regardless of .env
@pytest.fixture(autouse=True)
def fixed_settings():
    from app.config import Settings
    with patch("app.jobs.scheduler.get_settings") as mock:
        s = Settings(
            database_url="sqlite:///:memory:",
            zombie_window_days=30,
        )
        mock.return_value = s
        yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_prune_removes_old_rows(db):
    old_ts = datetime.now(UTC) - timedelta(days=40)
    db.add(_make_event(old_ts))
    db.commit()

    deleted = prune_stale_traffic(db)
    assert deleted == 1
    assert db.query(TrafficEvent).count() == 0


def test_prune_preserves_recent_rows(db):
    recent_ts = datetime.now(UTC) - timedelta(days=10)
    db.add(_make_event(recent_ts))
    db.commit()

    deleted = prune_stale_traffic(db)
    assert deleted == 0
    assert db.query(TrafficEvent).count() == 1


def test_prune_mixed_ages(db):
    now = datetime.now(UTC)
    for days_ago in (5, 15, 35, 45, 60):
        db.add(_make_event(now - timedelta(days=days_ago)))
    db.commit()

    deleted = prune_stale_traffic(db)
    # rows at 35, 45, 60 days are beyond the 30-day window
    assert deleted == 3
    assert db.query(TrafficEvent).count() == 2


def test_prune_chunked_deletion(db):
    """When more rows exist than the chunk size, all are eventually deleted."""
    old_ts = datetime.now(UTC) - timedelta(days=60)
    for _ in range(25):
        db.add(_make_event(old_ts))
    db.commit()

    deleted = prune_stale_traffic(db, chunk_size=10)
    assert deleted == 25
    assert db.query(TrafficEvent).count() == 0


def test_prune_empty_table_returns_zero(db):
    deleted = prune_stale_traffic(db)
    assert deleted == 0
