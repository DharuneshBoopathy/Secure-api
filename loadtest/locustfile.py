"""Locust load test for the ingest path — the highest-volume write endpoint.

Run (from the repo root, against a running backend):

    python -m locust -f loadtest/locustfile.py --host http://127.0.0.1:8000 \
        --headless -u 50 -r 10 -t 60s

Set MONITOR_API_KEY to the key the target backend was started with.
See loadtest/README.md for how to establish a baseline and what the
published numbers in the README were measured on.
"""

import os
import random
import time

from locust import HttpUser, between, events, task

API_KEY = os.environ.get("MONITOR_API_KEY", "")
BATCH_SIZE = int(os.environ.get("LOADTEST_BATCH_SIZE", "25"))

SAMPLE_PATHS = [
    "/api/users",
    "/api/orders",
    "/api/payments/transfer",
    "/health",
    "/api/reports?type=monthly",
]


@events.test_start.add_listener
def _check_key(environment, **_kwargs):
    if not API_KEY:
        raise SystemExit(
            "MONITOR_API_KEY is not set — the ingest endpoints require it. "
            "See loadtest/README.md."
        )


def _event() -> dict:
    return {
        "method": "GET" if random.random() < 0.7 else "POST",  # nosec B311 — load shaping, not security
        "path": random.choice(SAMPLE_PATHS),  # nosec B311
        "status_code": 500 if random.random() < 0.05 else 200,  # nosec B311
        "latency_ms": random.random() * 200,  # nosec B311
        "body_bytes": random.randint(0, 2000),  # nosec B311
        "request_size_bytes": random.randint(0, 1000),  # nosec B311
        "response_size_bytes": random.randint(0, 4000),  # nosec B311
    }


class IngestUser(HttpUser):
    """Posts batches of synthetic traffic events, the shape a gateway log
    shipper would produce."""

    wait_time = between(0.1, 0.5)

    @task(10)
    def ingest_batch(self):
        payload = {"events": [_event() for _ in range(BATCH_SIZE)]}
        self.client.post(
            "/api/ingest/batch",
            json=payload,
            headers={"X-Monitor-Key": API_KEY},
            name="POST /api/ingest/batch",
        )

    @task(1)
    def read_stats(self):
        """A dashboard poll running concurrently with ingest — this is what
        actually contends with the write path for connection-pool slots."""
        self.client.get(
            "/api/inventory/stats",
            headers={"X-Monitor-Key": API_KEY},
            name="GET /api/inventory/stats",
        )


class TrafficStreamUser(HttpUser):
    """Holds an SSE connection open, as the Live Traffic page does.

    Locust has no SSE client; this uses a plain streaming GET and reads for a
    bounded window, which is enough to measure the connection cost and
    whether long-lived readers starve the pool — not to validate event
    delivery semantics (the vitest/Playwright suites cover that).
    """

    wait_time = between(5, 10)
    # Opt in explicitly: mixing this into a default run makes the ingest
    # percentiles harder to read. Select with `--class-picker` or by
    # commenting out the other class.
    abstract = True

    @task
    def stream(self):
        start = time.monotonic()
        with self.client.get(
            f"/api/traffic/stream?auth={API_KEY}",
            stream=True,
            catch_response=True,
            name="GET /api/traffic/stream",
        ) as resp:
            for _ in resp.iter_lines():
                if time.monotonic() - start > 10:
                    break
            resp.success()
