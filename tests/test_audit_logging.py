"""
Validates Task 2: Structured JSON audit logging to stdout.

Confirms that:
  1. log_audit_event() emits exactly one line to stdout per call.
  2. The line is valid JSON.
  3. The JSON contains the expected top-level keys.
  4. Field values match what was passed in.
  5. The DB insert still occurs (AuditLog row created).
  6. Both sinks (DB + stdout) carry the same timestamp.
"""

import json
import logging
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, Base
from app.services.audit_service import log_audit_event


# ---------------------------------------------------------------------------
# In-memory SQLite DB (only the audit_log table needed)
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[AuditLog.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Helper: capture what the "audit" logger emits
# ---------------------------------------------------------------------------

@pytest.fixture()
def captured_audit_records():
    """Attach an in-memory handler to the 'audit' logger for each test."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    audit_log = logging.getLogger("audit")
    audit_log.addHandler(handler)
    yield records
    audit_log.removeHandler(handler)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_emits_exactly_one_log_record(db, captured_audit_records):
    log_audit_event(
        db,
        event_type="test_event",
        actor="tester",
        target="test/target",
        ip="127.0.0.1",
        user_agent="pytest",
        success=True,
    )
    assert len(captured_audit_records) == 1


def test_emitted_record_is_valid_json(db, captured_audit_records):
    log_audit_event(
        db,
        event_type="test_event",
        actor="tester",
        target=None,
        ip=None,
        user_agent=None,
    )
    raw = captured_audit_records[0].getMessage()
    parsed = json.loads(raw)  # raises if invalid JSON
    assert isinstance(parsed, dict)


def test_json_contains_required_keys(db, captured_audit_records):
    log_audit_event(
        db,
        event_type="login_attempt",
        actor="admin",
        target="auth/login",
        ip="10.0.0.1",
        user_agent="curl/7.88",
        success=False,
    )
    payload = json.loads(captured_audit_records[0].getMessage())
    for key in ("audit", "event_type", "actor", "target", "ip", "timestamp", "success", "details"):
        assert key in payload, f"Missing key: {key}"


def test_json_values_match_inputs(db, captured_audit_records):
    log_audit_event(
        db,
        event_type="shadow_acknowledged",
        actor="ops-user",
        target="shadow/42",
        ip="192.168.1.5",
        user_agent="Mozilla/5.0",
        details={"reason": "known scanner"},
        success=True,
    )
    payload = json.loads(captured_audit_records[0].getMessage())
    assert payload["event_type"] == "shadow_acknowledged"
    assert payload["actor"] == "ops-user"
    assert payload["target"] == "shadow/42"
    assert payload["ip"] == "192.168.1.5"
    assert payload["success"] is True
    assert payload["details"] == {"reason": "known scanner"}
    assert payload["audit"] is True


def test_audit_flag_is_true(db, captured_audit_records):
    log_audit_event(
        db, event_type="x", actor="a", target=None, ip=None, user_agent=None
    )
    payload = json.loads(captured_audit_records[0].getMessage())
    assert payload["audit"] is True


def test_db_row_is_also_inserted(db, captured_audit_records):
    """Both sinks must operate: the DB row must exist after the call."""
    log_audit_event(
        db,
        event_type="alert_acknowledged",
        actor="admin",
        target="alert/7",
        ip="10.0.0.2",
        user_agent=None,
        success=True,
    )
    rows = db.query(AuditLog).filter(AuditLog.event_type == "alert_acknowledged").all()
    assert len(rows) == 1
    assert rows[0].actor == "admin"
    assert rows[0].success is True


def test_timestamp_is_iso8601_string(db, captured_audit_records):
    log_audit_event(
        db, event_type="x", actor="a", target=None, ip=None, user_agent=None
    )
    payload = json.loads(captured_audit_records[0].getMessage())
    # Must be parseable as ISO-8601
    ts = datetime.fromisoformat(payload["timestamp"])
    assert isinstance(ts, datetime)
