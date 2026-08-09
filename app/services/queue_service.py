import json
import logging
from functools import lru_cache

import redis

from app.config import get_settings

log = logging.getLogger(__name__)

STREAM_NAME = "apimonitor:ingest"
DEAD_LETTER_STREAM = "apimonitor:ingest:dead"
CONSUMER_GROUP = "ingest_workers"
# After this many failed processing attempts a message is moved to
# DEAD_LETTER_STREAM instead of being retried again — a permanently
# malformed event (or a bug triggered by one specific payload) would
# otherwise loop forever between XREADGROUP and a retry XADD.
MAX_RETRIES = 5


@lru_cache
def get_redis_client() -> "redis.Redis | None":
    """None when REDIS_URL isn't configured. Every ingest.py call site
    treats that as "queueing disabled, process inline instead" — a
    deployment that never sets REDIS_URL behaves exactly like it did before
    this module existed. lru_cache mirrors app.config.get_settings: one
    client per process, reused across requests."""
    url = get_settings().redis_url
    if not url:
        return None
    return redis.Redis.from_url(url, decode_responses=True)


def ensure_consumer_group(client: "redis.Redis") -> None:
    """Idempotent: always attempts XGROUP CREATE and swallows BUSYGROUP,
    rather than memoizing "already done" in-process. A restarted/failed-over
    Redis (data loss, FLUSHALL) can lose the group even though this process
    never restarted — a per-process flag would then silently never recreate
    it, so XREADGROUP/XACK would fail with NOGROUP from then on."""
    try:
        client.xgroup_create(STREAM_NAME, CONSUMER_GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def enqueue_event(client: "redis.Redis", event: dict) -> None:
    """event must contain org_id plus every keyword process_single_event
    needs besides db/model/commit/templates (see app.worker._handle_message,
    which is the other end of this contract)."""
    ensure_consumer_group(client)
    client.xadd(STREAM_NAME, {"payload": json.dumps({**event, "_retry": 0})})


def queue_depth(client: "redis.Redis") -> int:
    try:
        return client.xlen(STREAM_NAME)
    except redis.RedisError:
        return 0
