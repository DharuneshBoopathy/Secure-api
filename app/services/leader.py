"""Leader election for the APScheduler jobs in app/jobs/scheduler.py.

BackgroundScheduler is process-local (see app/main.py's lifespan): with no
coordination, scaling the API to N replicas means N independent copies of
every scheduled job (retrain, prune, idle-scan, gauges) running on the same
interval — N-times duplicated work, not once cluster-wide. This module
elects a single leader replica via a Redis lock so the others skip their
copies of those jobs instead.

No-op (is_leader() always True) when REDIS_URL isn't configured: a single,
un-clustered deployment doesn't need coordination, and behaves exactly as
it did before Phase 5.
"""

import logging
import threading
import uuid

import redis

from app.services.queue_service import get_redis_client

log = logging.getLogger(__name__)

LEADER_KEY = "apimonitor:scheduler:leader"
LOCK_TTL_SECONDS = 30
RENEW_INTERVAL_SECONDS = 10

# Compare-and-set via Lua so a replica can only renew/release a lock it
# actually holds — without this, replica A renewing after its lock already
# expired and was acquired by replica B would silently steal leadership
# back from B (both then think they're the leader).
_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
else
    return 0
end
"""
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class _LeaderElection:
    def __init__(self) -> None:
        self.instance_id = str(uuid.uuid4())
        self.is_leader = True  # single-instance default until start() says otherwise
        self._client: redis.Redis | None = None
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    def _tick(self, client) -> None:
        try:
            if self.is_leader:
                renewed = client.eval(_RENEW_SCRIPT, 1, LEADER_KEY, self.instance_id, LOCK_TTL_SECONDS * 1000)
                self.is_leader = bool(renewed)
            else:
                acquired = client.set(LEADER_KEY, self.instance_id, nx=True, px=LOCK_TTL_SECONDS * 1000)
                self.is_leader = bool(acquired)
        except Exception:
            log.exception("Leader election tick failed; assuming not leader until next tick succeeds")
            self.is_leader = False

    def start(self) -> None:
        self._client = get_redis_client()
        if self._client is None:
            self.is_leader = True
            return

        self.is_leader = False
        self._stop_event = threading.Event()
        self._tick(self._client)  # attempt to become leader immediately, don't wait a full interval

        def _loop() -> None:
            while self._stop_event is not None and not self._stop_event.wait(RENEW_INTERVAL_SECONDS):
                self._tick(self._client)

        self._thread = threading.Thread(target=_loop, daemon=True, name="leader-election")
        self._thread.start()

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._client is not None and self.is_leader:
            try:
                self._client.eval(_RELEASE_SCRIPT, 1, LEADER_KEY, self.instance_id)
            except Exception:  # nosec B110 — best-effort: the TTL expires this lock on its own regardless
                log.warning("Failed to release leader lock on shutdown; it will expire via TTL instead")
        self.is_leader = False


_election = _LeaderElection()


def start() -> None:
    _election.start()


def stop() -> None:
    _election.stop()


def is_leader() -> bool:
    return _election.is_leader
