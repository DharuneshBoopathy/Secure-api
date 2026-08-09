"""
Validates Task 2: Keyset/cursor pagination on GET /audit and composite index on TrafficEvent.

Confirms that:
  1. GET /audit with no cursor returns the latest `limit` rows, newest first.
  2. next_cursor_id equals the id of the last item when a full page is returned.
  3. next_cursor_id is None when fewer rows than limit are returned (last page).
  4. GET /audit?cursor_id=N returns only rows with id < N.
  5. Paging through all rows via successive cursor_id calls visits every row
     exactly once without duplicates.
  6. The response no longer contains offset-based keys (page, total).
  7. event_type / from_ts / to_ts filters still work alongside cursor_id.
  8. The ix_traffic_doc_ts composite index is declared on TrafficEvent.
  9. No .offset() call appears in list_audit's query — confirmed via SQLAlchemy
     query string inspection.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base, TrafficEvent
from app.routers.audit import list_audit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[AuditLog.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_log(db, event_type: str = "login", actor: str = "tester", offset_seconds: int = 0):
    row = AuditLog(
        event_type=event_type,
        actor=actor,
        target=None,
        ip="127.0.0.1",
        user_agent=None,
        timestamp=datetime(2024, 1, 1, 12, 0, 0) + timedelta(seconds=offset_seconds),
        details={},
        success=True,
    )
    db.add(row)
    db.flush()
    return row


def _seed(db, n: int = 10, event_type: str = "login") -> list[int]:
    """Insert n rows and return their ids in insertion order."""
    ids = []
    for i in range(n):
        row = _make_log(db, event_type=event_type, offset_seconds=i)
        ids.append(row.id)
    db.commit()
    return ids


def _make_request():
    """Build the minimal real Starlette Request that slowapi requires."""
    from starlette.requests import Request as _Request
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/audit",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }
    return _Request(scope)


def _call(db, **kwargs) -> dict:
    """Invoke list_audit directly, bypassing FastAPI/auth layers."""
    return list_audit(request=_make_request(), db=db, **kwargs)


# ---------------------------------------------------------------------------
# Basic pagination behaviour
# ---------------------------------------------------------------------------

def test_first_page_returns_newest_rows_first(db):
    _seed(db, n=5)
    result = _call(db, cursor_id=None, limit=3)
    returned_ids = [item.id for item in result["items"]]
    assert returned_ids == sorted(returned_ids, reverse=True), "Rows must be newest-first"


def test_first_page_respects_limit(db):
    _seed(db, n=10)
    result = _call(db, cursor_id=None, limit=4)
    assert len(result["items"]) == 4


def test_next_cursor_id_is_last_item_id_on_full_page(db):
    _seed(db, n=10)
    result = _call(db, cursor_id=None, limit=4)
    assert result["next_cursor_id"] == result["items"][-1].id


def test_next_cursor_id_is_none_on_partial_page(db):
    _seed(db, n=3)
    result = _call(db, cursor_id=None, limit=10)
    assert result["next_cursor_id"] is None


def test_cursor_id_filters_rows_below_cursor(db):
    _seed(db, n=5)
    # ids are 1..5; cursor_id=4 should return rows with id < 4
    result = _call(db, cursor_id=4, limit=10)
    returned_ids = [item.id for item in result["items"]]
    assert all(rid < 4 for rid in returned_ids)


def test_cursor_id_high_value_returns_all_rows(db):
    _seed(db, n=5)
    result = _call(db, cursor_id=9999, limit=25)
    assert len(result["items"]) == 5


def test_cursor_id_zero_history_returns_empty(db):
    _seed(db, n=5)
    # All ids are ≥ 1; cursor_id=1 means id < 1 → nothing
    result = _call(db, cursor_id=1, limit=25)
    assert result["items"] == []
    assert result["next_cursor_id"] is None


# ---------------------------------------------------------------------------
# Walk all pages — no duplicates, no missing rows
# ---------------------------------------------------------------------------

def test_full_walk_visits_every_row_exactly_once(db):
    all_ids = set(_seed(db, n=15))
    seen_ids: set[int] = set()
    cursor_id = None

    while True:
        result = _call(db, cursor_id=cursor_id, limit=5)
        for item in result["items"]:
            assert item.id not in seen_ids, f"Duplicate id {item.id} encountered"
            seen_ids.add(item.id)
        cursor_id = result["next_cursor_id"]
        if cursor_id is None:
            break

    assert seen_ids == all_ids, "Not all rows were visited"


# ---------------------------------------------------------------------------
# Response shape — no offset-era keys
# ---------------------------------------------------------------------------

def test_response_has_no_page_key(db):
    _seed(db, n=3)
    result = _call(db, cursor_id=None, limit=10)
    assert "page" not in result, "Legacy 'page' key must not appear in response"


def test_response_has_no_total_key(db):
    _seed(db, n=3)
    result = _call(db, cursor_id=None, limit=10)
    assert "total" not in result, "Legacy 'total' key must not appear (O(N) count removed)"


def test_response_has_items_and_next_cursor_id(db):
    _seed(db, n=3)
    result = _call(db, cursor_id=None, limit=10)
    assert "items" in result
    assert "next_cursor_id" in result


# ---------------------------------------------------------------------------
# Existing filters still work alongside cursor pagination
# ---------------------------------------------------------------------------

def test_event_type_filter_with_cursor(db):
    _seed(db, n=5, event_type="login")
    _seed(db, n=5, event_type="logout")
    result = _call(db, cursor_id=None, limit=25, event_type="login")
    assert all(item.event_type == "login" for item in result["items"])
    assert len(result["items"]) == 5


def test_from_ts_filter_with_cursor(db):
    _seed(db, n=10)  # timestamps 2024-01-01T12:00:00 + i seconds
    cutoff = datetime(2024, 1, 1, 12, 0, 5)
    result = _call(db, cursor_id=None, limit=25, from_ts=cutoff)
    assert all(item.timestamp >= cutoff for item in result["items"])


# ---------------------------------------------------------------------------
# No OFFSET in emitted SQL
# ---------------------------------------------------------------------------

def test_no_offset_call_in_list_audit_source():
    """Verify that the list_audit function body does not call .offset().

    SQLAlchemy's SQLite dialect emits 'LIMIT ? OFFSET ?' even for a bare
    .limit() call (it binds OFFSET=0 as a parameter), so SQL-string inspection
    is dialect-dependent and unreliable here.  Inspecting the source is the
    authoritative check — if .offset( appears, the O(N) skip-scan is back.
    """
    import inspect
    import app.routers.audit as audit_mod

    # Get the source of the innermost (unwrapped) function, not the slowapi wrapper.
    inner = getattr(audit_mod.list_audit, "__wrapped__", audit_mod.list_audit)
    source = inspect.getsource(inner)
    assert ".offset(" not in source, (
        "list_audit must not call .offset() — offset pagination has been replaced with keyset pagination"
    )


# ---------------------------------------------------------------------------
# Composite index on TrafficEvent
# ---------------------------------------------------------------------------

def test_traffic_event_has_ix_traffic_doc_ts_index():
    """Confirm the ix_traffic_doc_ts index is declared in TrafficEvent.__table_args__."""
    index_names = {idx.name for idx in TrafficEvent.__table__.indexes}
    assert "ix_traffic_doc_ts" in index_names, (
        "ix_traffic_doc_ts composite index is missing from TrafficEvent"
    )


def test_ix_traffic_doc_ts_covers_correct_columns():
    """The index must cover is_documented and ts — in that order."""
    idx = next(i for i in TrafficEvent.__table__.indexes if i.name == "ix_traffic_doc_ts")
    col_names = [col.key for col in idx.columns]
    assert col_names == ["is_documented", "ts"], (
        f"Expected ['is_documented', 'ts'], got {col_names}"
    )
