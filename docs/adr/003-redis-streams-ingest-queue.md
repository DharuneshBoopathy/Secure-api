# 003 — Redis Streams for the ingest queue

## Context

`POST /api/ingest/*` wrote to MySQL and ran scikit-learn inference
synchronously inside the HTTP request. For each event that meant: a
`TrafficEvent` INSERT, a `flush()` to get its primary key, an
IsolationForest + LOF `decision_function()` call, conditional `Alert`
inserts, and shadow/discovery bookkeeping — all before the response was
returned. Under sustained ingest that ties up a worker per in-flight event
and makes p99 latency a function of model inference time, which is exactly
the wrong coupling for a firehose endpoint whose callers (nginx log
shippers, gateway sidecars) don't care about the response body.

Two other Phase 5 requirements independently needed a shared datastore:
distributed rate limiting (slowapi's in-memory counters are per-process, so
N replicas silently enforce N× the intended limit) and scheduler leader
election (see ADR 004). Adding a queue technology that *isn't* also usable
for those two would mean running two pieces of infrastructure where one
would do.

## Decision

Redis Streams, with a consumer group, consumed by a separate worker process
(`app/worker.py`, run as its own container / K8s Deployment).

Redis over the alternatives considered:

* **Kafka** — the right answer at genuinely high throughput, but it's a
  substantial operational commitment (ZooKeeper/KRaft, partition planning,
  consumer-group rebalancing semantics) for a workload that has not yet
  demonstrated it needs those guarantees. The master prompt for this work
  explicitly said to avoid Kafka unless throughput demands it.
* **Celery + Redis** — adds a task-abstraction layer and its own worker
  lifecycle on top of the same Redis we'd be running anyway. The payload
  here is a flat dict of scalars going to one known handler; the abstraction
  buys nothing and costs a dependency.
* **Redis Lists (LPUSH/BRPOP)** — simpler, but a crashed consumer loses the
  message it had popped. Streams' consumer groups keep a pending-entries
  list, which is what makes at-least-once redelivery possible at all.

Key properties of the implementation:

* **Opt-in.** `REDIS_URL` unset (the default) means `get_redis_client()`
  returns `None` and every ingest endpoint processes inline exactly as
  before. A single-box deployment needs no Redis at all, and the change is
  not a breaking one for existing installs.
* **At-least-once, not exactly-once.** Messages are XACKed after the handler
  returns. A crash between DB commit and XACK re-delivers the event, so
  duplicate `TrafficEvent` rows are possible. Accepted: this is analytics
  traffic where a duplicated row perturbs counts marginally, and the
  alternative (an idempotency key per event, and the storage/lookup cost of
  enforcing it on every insert) is not worth paying at this value density.
* **Bounded retries with a dead-letter stream.** After `MAX_RETRIES` (5) a
  message moves to `apimonitor:ingest:dead` rather than being retried
  forever — a permanently malformed payload would otherwise loop between
  XREADGROUP and a retry XADD indefinitely, and the retry itself would keep
  the queue depth metric permanently non-zero.
* **Stale-message reclaim.** `XAUTOCLAIM` with a 60s idle threshold hands
  messages from a crashed consumer to a live one; without it, a worker that
  dies mid-batch strands its pending entries permanently.

## Consequences

**Good.** Ingest endpoints return as soon as the XADD completes, so response
time no longer includes model inference. Workers scale independently of the
API. The same Redis backs distributed rate limiting and leader election, so
one dependency covers three requirements.

**Bad / accepted.** Redis becomes a hard dependency *when enabled* — if it's
down and `REDIS_URL` is set, ingest fails rather than silently falling back
to inline processing. That fallback was deliberately not implemented:
events sent seconds apart taking different code paths would make debugging
ingestion problems considerably harder than a clean failure does.

Ingest is now eventually-consistent: an event acknowledged by the API may
not be queryable for a moment. The e2e tests had to account for this, and
any future "did my event land?" UX needs to as well.

Trace context does not currently propagate across the queue boundary (see
ADR 005 and `app/tracing.py`) — the HTTP hop and the worker hop are each
traced, but not stitched into one trace.
