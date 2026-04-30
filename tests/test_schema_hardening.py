"""
Validates Task 1: Pydantic strict-input enforcement on ingest schemas.

Confirms that:
  1. Extra / unknown fields on IngestBatchItem are rejected (extra="forbid").
  2. Extra / unknown fields on NginxAccessLog are rejected (extra="forbid").
  3. path values exceeding 1024 chars are rejected on IngestBatchItem.
  4. uri values exceeding 1024 chars are rejected on NginxAccessLog.
  5. client_ip values exceeding 64 chars are rejected on IngestBatchItem.
  6. remote_addr values exceeding 64 chars are rejected on NginxAccessLog.
  7. Valid payloads (including edge cases) still pass.
"""

import pytest
from pydantic import ValidationError

from app.schemas import IngestBatchItem, NginxAccessLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def valid_batch_item(**overrides) -> dict:
    base = {"method": "GET", "path": "/health", "status_code": 200, "latency_ms": 5.0}
    return {**base, **overrides}


def valid_nginx_log(**overrides) -> dict:
    base = {"method": "GET", "uri": "/health", "status": 200}
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# extra="forbid" – IngestBatchItem
# ---------------------------------------------------------------------------

def test_ingest_batch_item_rejects_extra_fields():
    with pytest.raises(ValidationError) as exc_info:
        IngestBatchItem(**valid_batch_item(malicious_injection="value"))
    errors = exc_info.value.errors()
    assert any(e["type"] == "extra_forbidden" for e in errors)


def test_ingest_batch_item_rejects_multiple_extra_fields():
    with pytest.raises(ValidationError):
        IngestBatchItem(**valid_batch_item(foo="bar", baz=123))


# ---------------------------------------------------------------------------
# extra="forbid" – NginxAccessLog
# ---------------------------------------------------------------------------

def test_nginx_access_log_rejects_extra_fields():
    with pytest.raises(ValidationError) as exc_info:
        NginxAccessLog(**valid_nginx_log(malicious_injection="value"))
    errors = exc_info.value.errors()
    assert any(e["type"] == "extra_forbidden" for e in errors)


# ---------------------------------------------------------------------------
# max_length=1024 on path / uri
# ---------------------------------------------------------------------------

def test_ingest_batch_item_rejects_oversized_path():
    with pytest.raises(ValidationError):
        IngestBatchItem(**valid_batch_item(path="/" + "a" * 1024))


def test_ingest_batch_item_accepts_path_at_limit():
    item = IngestBatchItem(**valid_batch_item(path="/" + "a" * 1023))
    assert len(item.path) == 1024


def test_nginx_access_log_rejects_oversized_uri():
    with pytest.raises(ValidationError):
        NginxAccessLog(**valid_nginx_log(uri="/" + "x" * 1024))


def test_nginx_access_log_accepts_uri_at_limit():
    log = NginxAccessLog(**valid_nginx_log(uri="/" + "x" * 1023))
    assert len(log.uri) == 1024


# ---------------------------------------------------------------------------
# max_length=64 on IP fields
# ---------------------------------------------------------------------------

def test_ingest_batch_item_rejects_oversized_client_ip():
    with pytest.raises(ValidationError):
        IngestBatchItem(**valid_batch_item(client_ip="1.2.3." + "4" * 62))


def test_ingest_batch_item_accepts_valid_ip():
    item = IngestBatchItem(**valid_batch_item(client_ip="192.168.1.1"))
    assert item.client_ip == "192.168.1.1"


def test_nginx_access_log_rejects_oversized_remote_addr():
    with pytest.raises(ValidationError):
        NginxAccessLog(**valid_nginx_log(remote_addr="1.2.3." + "4" * 62))


def test_nginx_access_log_accepts_valid_remote_addr():
    log = NginxAccessLog(**valid_nginx_log(remote_addr="10.0.0.1"))
    assert log.remote_addr == "10.0.0.1"


# ---------------------------------------------------------------------------
# Regression: valid full payloads still accepted
# ---------------------------------------------------------------------------

def test_ingest_batch_item_full_valid_payload():
    item = IngestBatchItem(
        method="POST",
        path="/api/v1/users",
        status_code=201,
        latency_ms=12.3,
        client_ip="10.0.0.5",
        auth_present=True,
        body_bytes=256,
        gateway="nginx",
    )
    assert item.method == "POST"
    assert item.status_code == 201


def test_nginx_access_log_full_valid_payload():
    log = NginxAccessLog(
        ts="2024-01-01T00:00:00",
        remote_addr="10.0.0.1",
        method="GET",
        uri="/health",
        status=200,
        request_time=0.002,
        body_bytes_sent=128,
        gateway="nginx",
    )
    assert log.status == 200
