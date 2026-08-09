"""Standalone consumer for the Redis Streams ingest queue.

Only relevant when REDIS_URL is set (see app/config.py) — otherwise
/api/ingest/* processes events inline and this process has nothing to do.
Run as its own process/container: `python -m app.worker` (see the `worker`
service in docker-compose.yml and the Deployment in helm/).
"""

import json
import logging
import os
import signal
import socket

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.services import metrics as prom
from app.services.ml_anomaly import load_model
from app.services.queue_service import (
    CONSUMER_GROUP,
    DEAD_LETTER_STREAM,
    MAX_RETRIES,
    STREAM_NAME,
    ensure_consumer_group,
    get_redis_client,
)
from app.services.traffic_processor import process_single_event, refresh_gauges
from app.tracing import setup_worker_tracing

log = logging.getLogger("apimonitor.worker")

# A message pending (read but never XACKed) for longer than this almost
# always means the consumer that read it crashed mid-processing — reclaim_
# stale_messages hands it to a live consumer instead of leaving it stuck.
RECLAIM_IDLE_MS = 60_000


def _handle_message(db: Session, client, msg_id: str, fields: dict) -> None:
    payload = json.loads(fields["payload"])
    retry = payload.pop("_retry", 0)
    org_id = payload.pop("org_id")
    try:
        model = load_model(db, org_id)
        process_single_event(db, org_id=org_id, model=model, commit=True, **payload)
        refresh_gauges(db)
    except Exception:
        db.rollback()
        log.exception("Ingest message %s failed (attempt %d)", msg_id, retry + 1)
        if retry + 1 >= MAX_RETRIES:
            client.xadd(
                DEAD_LETTER_STREAM,
                {"payload": json.dumps({**payload, "org_id": org_id, "_retry": retry + 1, "_error": "max_retries_exceeded"})},
            )
            prom.INGEST_QUEUE_DEAD_LETTER_TOTAL.inc()
        else:
            client.xadd(STREAM_NAME, {"payload": json.dumps({**payload, "org_id": org_id, "_retry": retry + 1})})
    finally:
        client.xack(STREAM_NAME, CONSUMER_GROUP, msg_id)


def process_available_messages(db: Session, client, consumer_name: str, *, count: int = 50, block_ms: int = 1000) -> int:
    """Read and process up to `count` newly-delivered messages once. Split
    out from run()'s infinite loop so tests can drive one deterministic pass
    against fakeredis instead of needing a real blocking consumer thread."""
    ensure_consumer_group(client)
    resp = client.xreadgroup(CONSUMER_GROUP, consumer_name, {STREAM_NAME: ">"}, count=count, block=block_ms)
    processed = 0
    for _stream_name, messages in resp or []:
        for msg_id, fields in messages:
            _handle_message(db, client, msg_id, fields)
            processed += 1
    return processed


def reclaim_stale_messages(db: Session, client, consumer_name: str, *, count: int = 50) -> int:
    ensure_consumer_group(client)
    try:
        _cursor, messages, _deleted = client.xautoclaim(
            STREAM_NAME, CONSUMER_GROUP, consumer_name, min_idle_time=RECLAIM_IDLE_MS, start_id="0-0", count=count
        )
    except Exception:
        log.exception("xautoclaim failed")
        return 0
    for msg_id, fields in messages:
        _handle_message(db, client, msg_id, fields)
    return len(messages)


def run(stop_event=None) -> None:
    client = get_redis_client()
    if client is None:
        log.error("REDIS_URL is not configured; the ingest worker has nothing to consume. Exiting.")
        return

    setup_worker_tracing()

    consumer_name = f"worker-{socket.gethostname()}-{os.getpid()}"
    log.info("Ingest worker %s starting, consuming stream %s", consumer_name, STREAM_NAME)

    if stop_event is None:
        import threading

        stop_event = threading.Event()

        def _handle_signal(signum, _frame):
            log.info("Received signal %s, shutting down after the current batch", signum)
            stop_event.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

    db = SessionLocal()
    try:
        while not stop_event.is_set():
            reclaim_stale_messages(db, client, consumer_name)
            process_available_messages(db, client, consumer_name)
            try:
                prom.INGEST_QUEUE_DEPTH.set(client.xlen(STREAM_NAME))
            except Exception:  # nosec B110 — a transient XLEN failure shouldn't stop the consume loop; the gauge is just stale until the next successful tick
                log.warning("Failed to update ingest queue depth gauge")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run()
