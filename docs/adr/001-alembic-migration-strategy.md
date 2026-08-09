# 001 — Alembic migration strategy

## Context

Schema was previously managed by `Base.metadata.create_all()` at FastAPI
startup, plus a hand-rolled `ensure_phase1_schema()` in `app/database.py`
that ran a fixed list of `ALTER TABLE ... ADD COLUMN` statements to patch
`traffic_events` for installs that predated certain columns. This works for
a single-box prototype but doesn't scale: every future column/table change
would need another hand-written, order-dependent ALTER block, there's no
record of schema history, and nothing stops two API replicas from racing
`create_all()`/the ALTER block against each other on simultaneous startup.

Phase 2 (multi-tenancy) also needs a real migration — adding `org_id` to
eight existing tables and backfilling it — which is exactly the kind of
change `create_all()` cannot express at all (it only creates missing
tables/columns from scratch; it never alters or backfills existing ones).

## Decision

Adopt Alembic. `alembic/env.py` imports `app.database.Base` /
`app.models` and resolves the DB URL from `app.config.Settings` (same
env var → .env → secrets manager → `/run/secrets` → default chain the app
already uses), so there is one source of truth for the connection string.

**Baseline migration** (`alembic/versions/9a7f36609dac_baseline_schema.py`)
was generated via `alembic revision --autogenerate` against an empty
database and reproduces the current `create_all()` schema exactly,
including the MySQL-specific bits that hand-written DDL would be easy to
get wrong: `LONGTEXT` on `openapi_snapshots.raw_yaml`, and the
`mysql_length` prefix-indexes on `traffic_events.path` /
`shadow_endpoints.path_normalized` / `discovered_endpoints.path_normalized`
/ `traffic_daily_summary.path_normalized` (InnoDB's 3072-byte key limit
means a full `VARCHAR(1024)` can't be indexed outright under `utf8mb4`).
Verified two ways since this sandbox has no live MySQL: (1) autogenerate
against SQLite still preserves `mysql_length`/`LONGTEXT` because Alembic
renders them from the SQLAlchemy `Index`/`Column` objects in
`target_metadata`, not from the connected dialect; (2)
`alembic upgrade head --sql` against a `mysql+pymysql://` URL in offline
mode renders correct MySQL DDL (`path(191)`, `raw_yaml LONGTEXT`) without
needing a live connection.

**Startup wiring**: `alembic upgrade head` runs as a separate pre-start
step — `Dockerfile`'s `CMD` (`alembic upgrade head && uvicorn ...`) and
`make migrate` for bare-metal/local dev — not embedded in the FastAPI
`lifespan`. This matches how a real CD pipeline runs migrations (Phase
5.4: build → migrate → roll out) and avoids every replica racing the same
DDL on concurrent boot, which embedding it in the app process would not
fix on its own. `app/main.py` no longer calls `Base.metadata.create_all()`
or the removed `ensure_phase1_schema()`.

**Upgrading an existing (pre-Alembic) deployment**: the baseline migration
must not be re-run against a database that already has these tables from
`create_all()`. Operators upgrading an existing install run:

```bash
alembic stamp head   # record "already at baseline" without touching DDL
```

*once*, before deploying the first version that runs `alembic upgrade head`
automatically. A fresh database instead runs the baseline migration for
real and ends up in the identical state. This one-time step could not be
made automatic without either (a) probing for table existence and guessing
whether it's "old create_all() schema" vs. "some other database" — fragile
— or (b) shipping a data-loss-risking `DROP TABLE IF EXISTS` — unacceptable.
An explicit operator action is safer for a step that runs exactly once per
environment.

## Consequences

- All future schema changes (Phase 2's `org_id` columns included) go
  through `alembic revision --autogenerate` + review, not ad hoc DDL.
- Tests are unaffected: they build tables directly via
  `Base.metadata.create_all(engine, tables=[...])` against in-memory
  SQLite and never touch Alembic, matching the existing pattern (see
  `test_token_hashing.py`'s comment on why `OpenAPISnapshot` is excluded
  from SQLite-backed test fixtures — the same `LONGTEXT` limitation that
  affects this baseline's SQLite-side verification).
- New deployments run the migration automatically; existing ones need the
  one-time `alembic stamp head` documented above and in the README.
- Multiple replicas starting simultaneously still isn't handled by
  Alembic's own locking — orchestration should run migrations as a single
  pre-deploy step (e.g. a Kubernetes Job / CD pipeline stage) ahead of
  scaling up replicas, per Phase 5's CD pipeline task, rather than relying
  on each replica's own startup to serialize safely.
