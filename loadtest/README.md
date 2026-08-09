# Load testing

Two toolchains, because they answer different questions:

| File | Runner | What it covers |
|---|---|---|
| `locustfile.py` | Locust (pure Python, `pip install locust`) | `POST /api/ingest/batch` under concurrency, with a concurrent dashboard poll. **This is the one with published results below.** |
| `ingest_batch.js` | k6 (separate binary) | Same ingest path, for teams already standardised on k6. |
| `traffic_stream.js` | k6 **+ the `xk6-sse` extension** | The SSE `/api/traffic/stream` endpoint. Stock k6 has no SSE client — see the build note at the top of that file. |

The k6 scripts are reviewed but **have never been executed** — no k6 binary
was available in the environment they were written in. The Locust results
below are real measurements.

## Running (Locust)

```bash
pip install locust

# Terminal 1 — a backend pointed at a migrated database
DATABASE_URL=sqlite:///./loadtest_bench.db \
SECRET_KEY=loadtest-secret-key-minimum-32-characters-long \
MONITOR_API_KEY=loadtest-monitor-key-minimum-32-characters \
ADMIN_PASSWORD=LoadTestAdmin123! APP_ENV=development \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# Terminal 2
MONITOR_API_KEY=loadtest-monitor-key-minimum-32-characters \
python -m locust -f loadtest/locustfile.py --host http://127.0.0.1:8010 \
    --headless -u 20 -r 5 -t 45s --csv=loadtest/results/baseline
```

Tunables: `LOADTEST_BATCH_SIZE` (default 25 events per request), `-u`
(concurrent users), `-t` (duration).

## Measured baseline

**Configuration.** SQLite backing store, `REDIS_URL` unset (so ingest runs
**synchronously in-request** — no queue), one uvicorn worker, no ML model
trained yet, Windows dev laptop. 25 events per batch.

| Metric | 5 users | 20 users |
|---|---|---|
| Throughput | 2.75 batches/s | 2.96 batches/s |
| Ingest p50 | 900 ms | 6,100 ms |
| Ingest p95 | 4,100 ms | 14,000 ms |
| Ingest p99 | 5,700 ms | 17,000 ms |
| `GET /inventory/stats` p95 | 71 ms | 160 ms |
| Failures | 0 | 0 |

**Sustained ingest ≈ 70 events/s** (2.8 batches/s × 25) in this
configuration, with zero errors at both concurrency levels.

### What these numbers actually mean

Throughput is **flat** across a 4× increase in concurrency (2.75 → 2.96
batches/s) while latency scales almost **linearly** (p50 900 ms → 6,100 ms).
That is the signature of a serialized bottleneck, not of a saturated
application: extra concurrency just queues behind a lock rather than
producing extra work. Here that lock is **SQLite's single-writer
constraint** — every batch takes the write lock for its whole transaction.

So treat the absolute figures as a **floor, and as a property of SQLite**,
not as the platform's ceiling:

* **MySQL (the production database) will behave differently** — row-level
  locking and InnoDB's concurrent-writer support remove exactly the
  constraint that dominates this measurement. These numbers do not predict
  production throughput and should not be quoted as if they do.
* **Queued mode was not benchmarked.** With `REDIS_URL` set, the request
  path becomes a single `XADD` and the DB write moves to the worker, which
  should decouple response time from ingest cost entirely (that's the whole
  point of ADR 003). No Redis server was available in this environment, so
  that claim is reasoned, not measured.
* `GET /inventory/stats` stayed fast (p95 71–160 ms) throughout, i.e. the
  read path was not meaningfully starved by the write contention.

### Re-establishing the baseline properly

To turn this into a real SLO, re-run against a deployment that matches
production: MySQL, `REDIS_URL` set with worker replicas running, and the
`db_pool_size` / replica count you actually deploy (see the README's
"Connection pooling" section). Then record throughput and p95 for both
queued and synchronous modes, and update the table above with the
configuration you tested.
