# 004 — Scheduler leader election

## Context

`app/jobs/scheduler.py` registers six recurring jobs on an APScheduler
`BackgroundScheduler` that `app/main.py` starts inside the FastAPI lifespan.
`BackgroundScheduler` is process-local: it has no notion of other replicas.
Running N API replicas therefore runs N independent copies of every job on
the same interval.

For the write-side jobs that is actively harmful, not merely wasteful:

* `_retrain_ml` — N replicas each train a model per org and each call
  `save_model()`, which deactivates the previous version and inserts a new
  one. With `MAX_MODEL_VERSIONS = 5`, three replicas retraining
  simultaneously can churn through the entire retained version history in a
  single tick, destroying the rollback window ADR-less model versioning
  exists to provide.
* `_prune_stale_traffic` / `_traffic_rollup` — concurrent chunked deletes
  over the same rows; at best duplicated work, at worst rollup
  double-counting into `traffic_daily_summary` (which is UPSERTed by
  incrementing `request_count`, so a concurrent second run inflates it).
* `_idle_scan` — recomputes zombie state per org; two runners racing on the
  same rows produce interleaved writes.

## Decision

A Redis-backed leader lock (`app/services/leader.py`), with the write-side
jobs gated behind a `@_leader_only` decorator in the scheduler.

* Acquire with `SET key value NX PX 30000` — only one replica wins.
* Renew every 10s via a Lua compare-and-set script that extends the TTL
  **only if the stored value is still our instance ID**. A plain `PEXPIRE`
  would let a replica whose lock had already expired and been taken by
  another replica silently steal leadership back, leaving two leaders.
* Release on shutdown via the same compare-and-set pattern, so a
  non-leader's `stop()` can't delete someone else's lock.
* A Redis error during a renew tick sets `is_leader = False` rather than
  raising — losing the lock is the safe failure direction, since it means
  *fewer* runners, not more.

Alternatives considered:

* **A dedicated singleton scheduler container** (scale=1, no election).
  Simpler, and genuinely a good option — but it makes the scheduler a single
  point of failure with no automatic failover, and it means one more
  deployable unit and one more image role to keep in sync. Election gives
  failover for the cost of ~90 lines.
* **APScheduler's `SQLAlchemyJobStore` with a shared DB.** APScheduler does
  coordinate via the jobstore, but its locking is advisory and version-
  dependent, and it would put scheduler coordination traffic on the primary
  MySQL connection pool that ingest is already contending for.

### `_gauges` is deliberately NOT leader-gated

This is the non-obvious part. `_gauges` calls `update_prometheus_gauges()`,
which sets **this process's own in-memory `prometheus_client` gauge
objects**. Prometheus scrapes each replica's `/metrics` independently. If
only the leader refreshed its gauges, every non-leader would serve
permanently stale (or zero) values, and any aggregation across the scrape
targets would be wrong. The "runs N times" problem that motivates election
for the write jobs doesn't apply to a job whose only effect is on
process-local memory — there, running everywhere is the *correct* behavior.

## Consequences

**Good.** Write-side jobs run exactly once cluster-wide with automatic
failover: if the leader dies, its lock TTL expires within 30s and another
replica acquires it on its next tick.

**Bad / accepted.** Up to a 30s window after a leader dies where no
write-side job runs. Given the shortest interval among them is 30 minutes
(`_idle_scan`), a 30s gap is immaterial.

Leadership is not fenced. A leader that is network-partitioned from Redis
but still able to reach MySQL will believe it is not the leader (its renew
fails → `is_leader = False`), which is the safe direction. The unsafe
direction — a paused-then-resumed process acting on stale leadership — is
possible in principle but requires a GC/VM pause longer than the 30s TTL,
and the jobs in question are idempotent enough (chunked deletes, upserts,
recomputes) that a duplicate run is not corrupting.

With `REDIS_URL` unset, `is_leader()` is always `True` — a single-instance
deployment behaves exactly as it did before this existed.
