"""
Phase 4.1 (decouple ingestion from the request path): the Redis Streams
ingest queue and its worker.

Covers:
  1. queue_service.get_redis_client() is None when REDIS_URL isn't set —
     the default, unconfigured state.
  2. enqueue_event() XADDs a JSON payload (with a _retry counter) to the
     ingest stream via a real fakeredis client.
  3. ingest.py's _apply_nginx_log routes to the queue instead of writing to
     the DB synchronously when a Redis client is available, and still
     processes inline when it isn't (unchanged pre-Phase-4 behavior).
  4. POST /ingest/batch (via its unwrapped handler, bypassing the slowapi
     decorator — same pattern test_org_data_isolation.py uses) enqueues one
     message per event and returns {"queued": N} instead of writing rows.
  5. worker.process_available_messages consumes a queued message end-to-end
     and produces the same TrafficEvent a synchronous call would have.
  6. A message whose processing keeps failing is retried up to MAX_RETRIES
     times, then moved to the dead-letter stream and XACKed off the main one.
  7. worker.reclaim_stale_messages claims a message left pending by a
     crashed consumer and processes it.
"""

import json

import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.routers.ingest as ingest_mod
import app.worker as worker_mod
from app.models import Alert, Base, DiscoveredEndpoint, KnownEndpoint, MLModelState, ShadowEndpoint, TrafficEvent, ZombieEndpointState
from app.schemas import IngestBatch, IngestBatchItem, NginxAccessLog
from app.deps import OrgContext
from app.security import OrgRole
from app.services import queue_service
from app.services.queue_service import CONSUMER_GROUP, DEAD_LETTER_STREAM, MAX_RETRIES, STREAM_NAME, enqueue_event, get_redis_client

_TABLES = [
    TrafficEvent.__table__, Alert.__table__, DiscoveredEndpoint.__table__, ShadowEndpoint.__table__,
    KnownEndpoint.__table__, MLModelState.__table__, ZombieEndpointState.__table__,
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
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.flushall()


# ---------------------------------------------------------------------------
# get_redis_client default state
# ---------------------------------------------------------------------------

def test_get_redis_client_is_none_by_default():
    get_redis_client.cache_clear()
    try:
        assert get_redis_client() is None
    finally:
        get_redis_client.cache_clear()


# ---------------------------------------------------------------------------
# enqueue_event
# ---------------------------------------------------------------------------

def test_enqueue_event_xadds_payload_with_retry_counter(redis_client):
    enqueue_event(redis_client, {"org_id": 1, "method": "GET", "path": "/x"})
    entries = redis_client.xrange(STREAM_NAME)
    assert len(entries) == 1
    _msg_id, fields = entries[0]
    payload = json.loads(fields["payload"])
    assert payload == {"org_id": 1, "method": "GET", "path": "/x", "_retry": 0}


# ---------------------------------------------------------------------------
# ingest.py: queue vs inline
# ---------------------------------------------------------------------------

def test_apply_nginx_log_queues_when_redis_configured(db, redis_client, monkeypatch):
    monkeypatch.setattr(ingest_mod, "get_redis_client", lambda: redis_client)
    log = NginxAccessLog(method="GET", uri="/health", status=200, remote_addr="1.2.3.4", auth=None)

    queued = ingest_mod._apply_nginx_log(db, 1, log)

    assert queued is True
    assert db.query(TrafficEvent).count() == 0, "should not write synchronously once queued"
    assert redis_client.xlen(STREAM_NAME) == 1


def test_apply_nginx_log_processes_inline_when_redis_not_configured(db, monkeypatch):
    monkeypatch.setattr(ingest_mod, "get_redis_client", lambda: None)
    log = NginxAccessLog(method="GET", uri="/health", status=200, remote_addr="1.2.3.4", auth=None)

    queued = ingest_mod._apply_nginx_log(db, 1, log)

    assert queued is False
    assert db.query(TrafficEvent).count() == 1


def test_ingest_batch_enqueues_one_message_per_event(db, redis_client, monkeypatch):
    monkeypatch.setattr(ingest_mod, "get_redis_client", lambda: redis_client)
    ctx = OrgContext(org_id=1, role=OrgRole.EDITOR)
    batch = IngestBatch(events=[
        IngestBatchItem(method="GET", path="/a", status_code=200, latency_ms=1.0),
        IngestBatchItem(method="POST", path="/b", status_code=201, latency_ms=2.0),
    ])

    result = ingest_mod.ingest_batch.__wrapped__(request=_FakeRequest(), batch=batch, ctx=ctx, db=db)

    assert result == {"queued": 2}
    assert db.query(TrafficEvent).count() == 0
    assert redis_client.xlen(STREAM_NAME) == 2


# ---------------------------------------------------------------------------
# worker: happy path
# ---------------------------------------------------------------------------

def test_worker_consumes_queued_event_end_to_end(db, redis_client):
    enqueue_event(redis_client, {
        "org_id": 1, "method": "GET", "path": "/from-queue", "status_code": 200,
        "latency_ms": 5.0, "client_ip": None, "user_agent": "test", "auth_present": False,
        "body_bytes": 0, "request_size_bytes": 0, "response_size_bytes": 0, "content_type": None,
        "x_forwarded_for": None, "referer": None, "monitor_key": None, "session_id": None,
        "gateway": "test", "raw_ref": None,
    })

    processed = worker_mod.process_available_messages(db, redis_client, "worker-1", block_ms=10)

    assert processed == 1
    row = db.query(TrafficEvent).one()
    assert row.org_id == 1
    assert row.path == "/from-queue"
    # XACK removes it from the pending-entries list, not from the stream
    # itself (XLEN counts every entry ever added regardless of ack state).
    assert redis_client.xpending(STREAM_NAME, CONSUMER_GROUP)["pending"] == 0


# ---------------------------------------------------------------------------
# worker: retry then dead-letter
# ---------------------------------------------------------------------------

def test_worker_dead_letters_after_max_retries(db, redis_client, monkeypatch):
    def _always_fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_mod, "process_single_event", _always_fail)
    enqueue_event(redis_client, {"org_id": 1, "method": "GET", "path": "/bad", "status_code": 200, "latency_ms": 1.0})

    for _ in range(MAX_RETRIES):
        worker_mod.process_available_messages(db, redis_client, "worker-1", block_ms=10)

    assert redis_client.xpending(STREAM_NAME, CONSUMER_GROUP)["pending"] == 0, "should be acked off, not stuck pending"
    dead = redis_client.xrange(DEAD_LETTER_STREAM)
    assert len(dead) == 1
    dead_payload = json.loads(dead[0][1]["payload"])
    assert dead_payload["_retry"] == MAX_RETRIES
    assert dead_payload["_error"] == "max_retries_exceeded"


# ---------------------------------------------------------------------------
# worker: reclaim stale (crashed-consumer) messages
# ---------------------------------------------------------------------------

def test_reclaim_stale_messages_claims_and_processes(db, redis_client, monkeypatch):
    monkeypatch.setattr(worker_mod, "RECLAIM_IDLE_MS", 0)
    enqueue_event(redis_client, {
        "org_id": 1, "method": "GET", "path": "/orphaned", "status_code": 200,
        "latency_ms": 1.0, "client_ip": None, "user_agent": "test", "auth_present": False,
        "body_bytes": 0, "request_size_bytes": 0, "response_size_bytes": 0, "content_type": None,
        "x_forwarded_for": None, "referer": None, "monitor_key": None, "session_id": None,
        "gateway": "test", "raw_ref": None,
    })
    # Simulate consumer-a reading it and then crashing before XACK.
    queue_service.ensure_consumer_group(redis_client)
    redis_client.xreadgroup(CONSUMER_GROUP, "consumer-a-crashed", {STREAM_NAME: ">"}, count=10, block=10)

    reclaimed = worker_mod.reclaim_stale_messages(db, redis_client, "consumer-b-alive")

    assert reclaimed == 1
    row = db.query(TrafficEvent).one()
    assert row.path == "/orphaned"
    assert redis_client.xpending(STREAM_NAME, CONSUMER_GROUP)["pending"] == 0
