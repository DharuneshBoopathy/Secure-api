"""
Right-to-delete tests for app.services.traffic_processor.delete_traffic_for_client.

Covers:
  1. Deleting by client_ip removes only matching rows.
  2. Deleting by session_id removes only matching rows.
  3. Providing both deletes rows matching either identifier.
  4. Providing neither identifier is a no-op (returns 0, deletes nothing).
  5. Chunked deletion removes all matching rows when the count exceeds chunk_size.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, TrafficEvent
from app.services.traffic_processor import delete_traffic_for_client


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[TrafficEvent.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_event(*, client_ip: str | None = None, session_id: str | None = None) -> TrafficEvent:
    return TrafficEvent(
        org_id=1,
        method="GET",
        path="/test",
        status_code=200,
        latency_ms=5.0,
        body_bytes=0,
        client_ip=client_ip,
        session_id=session_id,
    )


def test_delete_by_client_ip_only_matching(db):
    db.add(_make_event(client_ip="10.0.0.1"))
    db.add(_make_event(client_ip="10.0.0.2"))
    db.commit()

    deleted = delete_traffic_for_client(db, client_ip="10.0.0.1")
    assert deleted == 1
    remaining = db.query(TrafficEvent).all()
    assert len(remaining) == 1
    assert remaining[0].client_ip == "10.0.0.2"


def test_delete_by_session_id_only_matching(db):
    db.add(_make_event(session_id="sess-a"))
    db.add(_make_event(session_id="sess-b"))
    db.commit()

    deleted = delete_traffic_for_client(db, session_id="sess-a")
    assert deleted == 1
    assert db.query(TrafficEvent).filter(TrafficEvent.session_id == "sess-b").count() == 1


def test_delete_by_either_identifier_when_both_given(db):
    db.add(_make_event(client_ip="10.0.0.1", session_id="sess-a"))
    db.add(_make_event(client_ip="10.0.0.9", session_id="sess-b"))
    db.add(_make_event(client_ip="10.0.0.9", session_id="sess-c"))
    db.commit()

    deleted = delete_traffic_for_client(db, client_ip="10.0.0.1", session_id="sess-b")
    assert deleted == 2
    remaining = db.query(TrafficEvent).all()
    assert len(remaining) == 1
    assert remaining[0].session_id == "sess-c"


def test_no_identifier_is_noop(db):
    db.add(_make_event(client_ip="10.0.0.1"))
    db.commit()

    deleted = delete_traffic_for_client(db)
    assert deleted == 0
    assert db.query(TrafficEvent).count() == 1


def test_chunked_deletion_removes_all_matching_rows(db):
    for _ in range(25):
        db.add(_make_event(client_ip="10.0.0.1"))
    db.commit()

    deleted = delete_traffic_for_client(db, client_ip="10.0.0.1", chunk_size=10)
    assert deleted == 25
    assert db.query(TrafficEvent).count() == 0
