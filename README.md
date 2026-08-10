# API Security Monitor

A runtime API governance platform. It ingests traffic from nginx logs, batch
event feeds, or PCAP uploads; builds a live inventory of every endpoint
actually being called; flags **shadow APIs** (serving traffic but absent from
your spec) and **zombie APIs** (documented but no longer used); and scores
every request with a per-organization ML anomaly detector that explains *why*
it flagged something.

Multi-tenant, with per-organization data isolation and a two-axis role model.

---

## Contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Security model](#security-model)
- [API reference](#api-reference)
- [Frontend](#frontend)
- [Scaling and deployment](#scaling-and-deployment)
- [Observability](#observability)
- [Data retention and privacy](#data-retention-and-privacy)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Known limitations](#known-limitations)

---

## Architecture

```
                    ┌───────────────────────────────────────────┐
                    │              nginx :80                    │
                    │   20 r/s rate limit · security headers    │
                    └────────────────────┬──────────────────────┘
                                         │
                    ┌────────────────────▼──────────────────────┐
                    │          FastAPI (uvicorn) :8000          │
                    │   /api/ingest/*  ·  /api/*  ·  React SPA   │
                    └────────────────────┬──────────────────────┘
                                         │
                 REDIS_URL unset ────────┴──────── REDIS_URL set
                        │                                │
                 process inline                    XADD, return
                        │                                │
                        │                  ┌─────────────▼─────────────┐
                        │                  │  Redis Streams            │
                        │                  │  queue · rate limits ·    │
                        │                  │  scheduler leader lock    │
                        │                  └─────────────┬─────────────┘
                        │                                │ XREADGROUP
                        │                  ┌─────────────▼─────────────┐
                        │                  │  app/worker.py (N pods)   │
                        └──────────┬───────┴─────────────┬─────────────┘
                                   │                     │
                    ┌──────────────▼─────────────────────▼──────────────┐
                    │              Traffic processor                    │
                    │  normalize path · detect shadow · ML score ·      │
                    │  explain · dedupe alerts                          │
                    └──────────────┬────────────────────────────────────┘
                                   │
                    ┌──────────────▼──────────┐   ┌─────────────────────┐
                    │       MySQL 8.0         │   │  APScheduler        │
                    │  (Alembic-managed)      │   │  leader-elected     │
                    └─────────────────────────┘   │  retrain·prune·scan │
                                                  └─────────────────────┘
              /metrics │                    │ OTLP spans        │ stdout
        ┌──────────────▼──────────┐  ┌──────▼───────┐  ┌────────▼────────┐
        │ Prometheus →Alertmanager│  │    Jaeger    │  │ Promtail → Loki │
        │        → Grafana        │  │   (traces)   │  │     (logs)      │
        └─────────────────────────┘  └──────────────┘  └─────────────────┘
```

The Redis / worker / tracing / log-shipping layer is **opt-in**. With
`REDIS_URL` and `OTEL_EXPORTER_OTLP_ENDPOINT` unset, ingestion runs inline in
the request and tracing is inert — a single-box deployment needs neither.

### Components

| Component | Location | Role |
|---|---|---|
| FastAPI app | `app/main.py` | Entry point, router registration, lifespan |
| Traffic processor | `app/services/traffic_processor.py` | Per-event normalization, classification, scoring |
| ML anomaly engine | `app/services/ml_anomaly.py` | Per-org IsolationForest + LOF ensemble, per-endpoint baselines, versioned and explainable |
| Discovery service | `app/services/discovery_service.py` | Shadow/zombie classification and risk scoring |
| Audit service | `app/services/audit_service.py` | Dual-sink logging (MySQL row + stdout JSON) |
| Scheduler | `app/jobs/scheduler.py` | Retrain, prune, idle-scan, gauges — leader-elected |
| Ingest queue | `app/services/queue_service.py`, `app/worker.py` | Optional Redis Streams decoupling |
| Leader election | `app/services/leader.py` | Optional; ensures scheduler write-jobs run once cluster-wide |
| Tracing | `app/tracing.py` | Optional OpenTelemetry, FastAPI → SQLAlchemy |
| Frontend SPA | `frontend/src/` | React + Vite + Tailwind, served by FastAPI in production |

### Data flow

1. Traffic arrives at `/api/ingest/*` (nginx log line, event batch, or PCAP).
2. Each event is path-normalized (`/users/123` → `/users/{id}`), matched
   against the registered endpoint set, and scored by that org's ML model.
3. Undocumented paths become **shadow endpoints** with a risk score.
4. Documented endpoints with declining traffic move through the **zombie
   lifecycle**: `ACTIVE → DECLINING → IDLE → ZOMBIE → DEAD`.
5. Anomalies and lifecycle changes raise **deduplicated alerts** carrying a
   feature-level explanation.
6. Raw events are kept 30 days, then rolled into `traffic_daily_summary`.

---

## Quick start

```bash
cp .env.example .env      # then fill in the required values
make setup                # generates strong random secrets into .env
make up                   # docker compose up --build
```

| Service | URL |
|---|---|
| Application (via nginx) | http://localhost |
| API + Swagger UI | http://localhost:8000/docs |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Jaeger (traces) | http://localhost:16686 |

Log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD` from your `.env`. First run
creates the bootstrap admin and a "Default Organization".

To run without the optional infrastructure, delete the `redis`, `worker`,
`jaeger`, `loki`, and `promtail` services from `docker-compose.yml` (or just
unset `REDIS_URL` / `OTEL_EXPORTER_OTLP_ENDPOINT` on `web`).

### Without Docker

The whole application runs on SQLite with no containers — useful for a quick
look or an air-gapped box. The schema is dialect-portable, so migrations
apply unchanged.

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..   # SPA is served by FastAPI

cat > .env <<'EOF'
APP_ENV=development
DATABASE_URL=sqlite:///./apimonitor.db
SECRET_KEY=local-dev-secret-key-at-least-32-characters-long-abc123
MONITOR_API_KEY=local-dev-monitor-key-at-least-32-characters-xyz789
ADMIN_USERNAME=admin
ADMIN_PASSWORD=AdminLocal123!
ALLOW_QUERY_AUTH=true
EOF

python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000 and sign in with those admin credentials.
SQLite serializes writes, so this path is for evaluation and development —
use MySQL for anything with real ingest volume (see
[`loadtest/README.md`](loadtest/README.md)).

---

## Local development

**Prerequisites:** Python 3.11+, Node.js 18+, Docker.

```bash
# 1. Dependencies only (MySQL, Prometheus, Grafana) in Docker
make dev

# 2. Backend
pip install -r requirements.txt
make migrate                       # alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3. Frontend (separate terminal) — dev server on :5173, proxies /api → :8000
cd frontend && npm install && npm run dev

# 4. Optional demo data
python scripts/seed_demo.py
```

| Target | Does |
|---|---|
| `make setup` | Generate `.env` with fresh random secrets |
| `make up` | Full stack via Docker Compose |
| `make dev` | Dependencies in Docker, app runs on host |
| `make migrate` | `alembic upgrade head` |
| `make test` | Backend test suite |
| `make build-frontend` | Production SPA build |
| `make logs` / `make down` / `make clean` | Logs, stop, stop+remove volumes |

### Database migrations

Schema is owned entirely by `alembic/`. The app does **not** call
`create_all()` — the Docker image runs `alembic upgrade head` before uvicorn
starts.

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "describe it"  # create after editing app/models.py
alembic downgrade -1                              # roll back one
```

**Upgrading a pre-Alembic deployment:** run `alembic stamp head` once before
deploying the first version that migrates automatically. See
[ADR 001](docs/adr/001-alembic-migration-strategy.md).

---

## Configuration

Read by `app/config.py` (pydantic-settings). Resolution order per field:
**environment variable → `.env` → external secrets manager → `/run/secrets/<name>` → default**.

### Required in production

| Variable | Description |
|---|---|
| `DATABASE_URL` | e.g. `mysql+pymysql://user:pass@host/db` |
| `SECRET_KEY` | JWT signing key, **min 32 chars**; startup fails if weak |
| `MONITOR_API_KEY` | Bootstrap key for automation clients (`X-Monitor-Key`) |
| `ADMIN_PASSWORD` | Bootstrap admin password; auto-generated and logged if unset |
| `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` | Docker Compose only |
| `GRAFANA_ADMIN_PASSWORD` | Docker Compose only |

### Optional

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `production` enables strict secret validation |
| `ADMIN_USERNAME` | `admin` | Bootstrap admin username |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `CORS_ORIGINS` | _(empty)_ | Comma-separated extra origins |
| `ANOMALY_THRESHOLD` | `0.8` | Score `[0–1]` above which an event is anomalous |
| `ML_RETRAIN_MINUTES` | `15` | Retrain interval (minimum 5) |
| `LOGIN_LOCKOUT_THRESHOLD` | `5` | Failed logins before lockout |
| `LOGIN_LOCKOUT_BASE_SECONDS` / `_MAX_SECONDS` | `30` / `900` | Lockout backoff and cap |
| `IDLE_THRESHOLD_HOURS` | `24` | Silence before an endpoint counts as idle |
| `ZOMBIE_WINDOW_DAYS` | `30` | Zombie lookback; also the raw-traffic retention window |
| `ZOMBIE_IDLE_THRESHOLD_DAYS` / `_DEAD_THRESHOLD_DAYS` | `14` / `30` | Lifecycle transitions |
| `DB_POOL_SIZE` / `DB_POOL_MAX_OVERFLOW` / `DB_POOL_TIMEOUT_SECONDS` | `10` / `20` / `30` | SQLAlchemy pool, per replica |
| `SECRETS_PROVIDER` | `env` | `vault`, `aws-secrets-manager`, or `gcp-secret-manager` |
| `ALLOW_QUERY_AUTH` | `false` | Accept `?auth=<token>`. **Required** for the SSE live features (Live Traffic, alert toasts) — `EventSource` cannot send headers |
| `REDIS_URL` | _(unset)_ | Enables ingest queue, distributed rate limits, leader election |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset)_ | Enables trace export |
| `ALERT_WEBHOOK_URL` | local no-op | Alertmanager receiver (Slack/PagerDuty/generic) |

**Connection pooling.** Connections per replica ≈ `DB_POOL_SIZE +
DB_POOL_MAX_OVERFLOW` under burst. Keep `replicas × that` comfortably under
MySQL's `max_connections`, leaving headroom for migrations and admin clients.

---

## Security model

### Authentication

JWT access + refresh tokens, or `X-Monitor-Key` for automation. Refresh
tokens are stored as SHA-256 hashes and rotated on every use.

**Reuse detection:** replaying an already-rotated refresh token revokes the
user's *entire* token chain, not just the replayed one, and audit-logs
`refresh_token_reuse`. The rotation itself is an atomic compare-and-swap, so
two concurrent refreshes can't both mint valid chains.

### Roles — two independent axes

**Platform roles** gate cross-tenant and account-level actions:

| Role | Can |
|---|---|
| `viewer` | Read own profile |
| `editor` | Above, plus issue API keys |
| `admin` | Above, plus manage users, read the platform audit log, right-to-delete, cross-org support access (audit-logged) |

**Organization roles** gate everything tenant-scoped (traffic, alerts,
inventory, registry, anomalies):

| Role | Can |
|---|---|
| `viewer` | Read the org's data |
| `editor` | Above, plus ingest, acknowledge, register endpoints |
| `owner` | Above, plus approve/reject members, change roles, rename, transfer ownership |

A platform `admin` is not automatically an org member — cross-org access is
possible but audit-logged as `cross_org_access`. See
[ADR 002](docs/adr/002-multi-tenancy-schema.md).

### Multi-tenancy

Every tenant-scoped table carries `org_id`. Requests select their
organization via the `X-Org-Id` header, falling back to the caller's sole
membership when unset. Isolation is verified end-to-end in
`tests/test_org_data_isolation.py`.

### Other controls

- **Account lockout** — after `LOGIN_LOCKOUT_THRESHOLD` consecutive failures,
  exponential backoff up to the cap; returns `423 Locked`. Audit-logged.
- **Admin MFA** — TOTP enrollment (`pyotp`), enforced at login for admins.
- **Password reset** — single-use SHA-256-hashed token, 30-minute lifetime,
  revokes all refresh tokens on redemption. No account enumeration. *There is
  no email integration:* the token is written to the application log for an
  operator to deliver. Wire this to a mail provider before production use.
- **Per-integration API keys** — issued, listed, and revoked individually,
  each bound to one organization with its own audit trail.
- **ML model signing** — the pickled model blob is HMAC-SHA256 signed with
  `SECRET_KEY` and verified before `pickle.loads`, closing the RCE surface
  even if an attacker can write to `ml_model_state`.
- **Security headers** — HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
  CSP, `Referrer-Policy`, `Permissions-Policy`; the `server` header is stripped.
- **No credential logging** — nginx maps `$http_authorization` to a boolean
  `auth_present` flag, and redacts the value of any `auth` query parameter
  before logging the URI. Raw JWTs and API keys never reach the access log by
  either route.
- **Query-parameter auth is opt-in** (`ALLOW_QUERY_AUTH`). The browser
  `EventSource` API cannot set request headers, so the two SSE endpoints
  accept `?auth=<token>`; this flag gates that. It is off by default and must
  be enabled for the Live Traffic page and alert toasts to work.
- **No third-party runtime assets** — the SPA loads no external fonts,
  scripts, or stylesheets, so the strict CSP (`default-src 'self'`) holds and
  the app functions in air-gapped deployments.

### Rate limiting

| Route group | Limit |
|---|---|
| `POST /api/auth/login` | 5 / min |
| `POST /api/auth/register` | 3 / min |
| `POST /api/auth/refresh` | 10 / min |
| `POST /api/auth/password-reset/*`, `/mfa/*` | 5 / min |
| `POST /api/auth/users`, `/api-keys` | 10 / min |
| `POST /api/ingest/*` | 500 / min |
| `GET /api/inventory/*` | 120 / min |
| `GET /api/audit` | 60 / min |
| `GET /api/traffic/stream`, `/api/alerts/stream` | 30 / min |

nginx adds an independent layer: 20 r/s sustained, burst 40, on all `/api/`.

slowapi's default in-memory storage is **per-process** — with multiple
replicas each enforces its own counters, multiplying the effective limit. Set
`REDIS_URL` to make limits correct cluster-wide.

### TLS

Designed to run behind a TLS-terminating proxy (ALB, Cloudflare, Traefik,
Caddy, or nginx with Let's Encrypt). The bundled nginx listens on :80 only.

`docker-compose.prod.yml` supplies that proxy for single-host deployments: it adds
Caddy on :80/:443 with automatic Let's Encrypt certificates in front of the existing
nginx, rebinds every other published port to loopback, and runs uvicorn with
`--proxy-headers` so rate limiting sees real client IPs.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build
```

See **[docs/deployment-oracle-free.md](docs/deployment-oracle-free.md)** for a complete
free-tier runbook (host provisioning, firewall, secrets, verification, backups).

---

## API reference

All routes are under `/api`. Swagger UI at `/docs`, ReDoc at `/redoc`.

### Auth — `/api/auth`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/login` | public | Issue access + refresh pair |
| `POST` | `/register` | public | Self-registration (creates a `viewer`) |
| `POST` | `/refresh` | public | Rotate refresh token |
| `POST` | `/logout` | public | Revoke refresh token |
| `POST` | `/password-reset/request` · `/confirm` | public | Token-based reset |
| `POST` | `/mfa/enroll` · `/enroll/confirm` · `/disable` | admin | TOTP lifecycle |
| `GET`/`POST`/`DELETE` | `/api-keys` · `/api-keys/{id}` | admin | Per-integration keys; plaintext returned once |
| `GET`/`PUT` | `/me` · `/me/password` | viewer | Own profile and password |
| `GET`/`POST`/`PATCH`/`DELETE` | `/users` · `/users/{id}` | admin | User administration |

### Organizations — `/api/orgs`

| Method | Path | Access | Description |
|---|---|---|---|
| `POST` · `GET` | `` | authenticated | Create an org (caller becomes owner) · list own orgs |
| `POST` | `/{id}/join-requests` | authenticated | Request to join (creates `pending`) |
| `GET` | `/{id}/members` | owner | List members, filter by status |
| `POST` | `/{id}/members/{uid}/approve` · `/reject` | owner | Decide a join request |
| `PATCH`/`DELETE` | `/{id}/members/{uid}` | owner | Change role · remove (kept as `revoked`) |
| `PATCH` | `/{id}` | owner | Rename |
| `POST` | `/{id}/transfer-ownership` | owner | Transfer; prior owner becomes editor |

### Ingestion — `/api/ingest`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/batch` | editor | Array of `IngestBatchItem` events |
| `POST` | `/nginx-json` · `/nginx-json-raw` | editor | Single nginx log line |
| `POST` | `/pcap` | editor | Wireshark `.pcap`, cleartext HTTP only, ≤50 MB |

```bash
curl -X POST http://localhost:8000/api/ingest/batch \
  -H "X-Monitor-Key: <key>" -H "Content-Type: application/json" \
  -d '{"events":[{"method":"GET","path":"/api/users/123","status_code":200,"latency_ms":12.5}]}'
```

With `REDIS_URL` set these enqueue instead of writing inline, and respond
`{"queued": N}` rather than `{"ingested": N, "skipped": N}`.

### Inventory — `/api/inventory`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `/discovered` · `/shadow` · `/idle` | viewer | Observed endpoints, undocumented only, idle only |
| `GET` | `/stats` | viewer | Dashboard counters |
| `GET` | `/traffic-trend?days=N` | viewer | Daily request/error series |

`traffic-trend` reads **both** stores: recent days aggregate live from
`traffic_events`, and days past the 30-day retention window come from
`traffic_daily_summary` (the raw rows are gone by then). Zero-filled so quiet
days aren't silently compressed.

### Registry — `/api/registry`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/openapi` | editor | Upload an OpenAPI spec (YAML) |
| `GET` | `/openapi/latest` | viewer | Most recent snapshot |
| `POST` | `/postman` | editor | Import a Postman Collection v2.x export |
| `POST` | `/curl` | editor | Import `curl` command lines |

All three converge on the same dedupe-by-`(org_id, method, path_template)`
logic. Postman/curl path variables (`{{var}}`, `:var`) and concrete example
values are templated to wildcards the same way OpenAPI's `{param}` is.

### Shadow, zombie, alerts, anomalies

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `/api/shadow` | viewer | Shadow endpoints with risk scores |
| `POST` | `/api/shadow/{id}/acknowledge` · `/add-to-registry` | editor | Review · promote to registered |
| `GET` | `/api/zombie` · `/summary` | viewer | Lifecycle states and counts |
| `POST` | `/api/zombie/{id}/retire` · `/reactivate` | editor | Retire · reactivate |
| `GET` | `/api/alerts` | viewer | List alerts |
| `GET` | `/api/alerts/stream` | viewer | SSE — **new** alerts only (no history replay); needs `ALLOW_QUERY_AUTH` |
| `POST` | `/api/alerts/{id}/ack` · `/feedback` | editor | Acknowledge · label true/false positive |
| `GET` | `/api/anomalies` | viewer | Events scored above `ANOMALY_THRESHOLD` |
| `GET` | `/api/traffic/stream` | viewer | SSE live traffic feed; needs `ALLOW_QUERY_AUTH` |

Shadow risk: `LOW` (read-only, <10 hits) → `CRITICAL` (write methods, ≥10 hits).

### ML models — `/api/ml-models`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | viewer | Version history: trained-at, sklearn version, sample count, active flag |
| `POST` | `/{id}/activate` | owner | Roll back or forward to a version |

### Privacy and audit

| Method | Path | Min role | Description |
|---|---|---|---|
| `DELETE` | `/api/privacy/traffic-data?client_ip=&session_id=` | admin | Right-to-delete |
| `GET` | `/api/audit` | admin | Keyset-paginated audit log |

Audit pagination is cursor-based (no `OFFSET` scan): pass `?cursor_id=` from
the previous response. Filters: `event_type`, `from_ts`, `to_ts`.

### Anomaly detection

An IsolationForest + LocalOutlierFactor ensemble, **one model per
organization** (never trained across tenants), plus a **per-endpoint
baseline** for any `(method, path template)` with ≥200 events in the window —
a `GET /health` and a `POST /payments/transfer` have very different normal
shapes, and one global model over both produces noise. Lower-volume endpoints
fall back to the org model.

Features: hour-of-day, day-of-week, status, latency, body size, auth
presence, path depth, method, path novelty, query param count, query Shannon
entropy, request/response size. High `query_entropy` is a strong SQL-injection
and BOLA signal.

Anomaly alerts carry `event_id` and an `explanation` — the top 3 features by
z-score against the model's own baseline:

```json
{"explanation": [
  {"feature": "query_entropy", "value": 5.1, "baseline_mean": 1.2, "z_score": 4.3}
]}
```

**Feedback loop.** Marking an alert `true_positive` excludes its event from
the next retrain's normal baseline, so a confirmed attack isn't folded into
"ordinary traffic". `false_positive` labels are recorded and surfaced but do
**not** auto-retune sensitivity — that would let anyone with editor access on
a compromised account silently suppress detections by mass-mislabeling. Treat
a rising false-positive rate as a prompt for human review.

Up to 5 versions are retained per org; `activate` is owner-gated because
swapping the model that scores every request is weightier than acknowledging
one alert. Activating a version that fails HMAC verification returns `422`.

---

## Frontend

React + Vite + TypeScript + Tailwind, with Zustand for state and TanStack
Query for server state. Built output is served by FastAPI in production.

| Page | Notes |
|---|---|
| Dashboard | Stat tiles, 30-day traffic trend, endpoint health mix; onboarding wizard on first run |
| Alerts | Cards with severity/type; click opens a detail drawer with the feature explanation and feedback buttons |
| Anomalies | Paginated table; row click opens the raw event plus its explanation |
| Shadow / Zombie / Discovered / Idle | Inventory views with acknowledge, promote, retire, reactivate |
| Connected APIs | Onboard by pasting a provider key — no spec needed |
| Registry | Upload OpenAPI, Postman, or curl |
| Members | Org switcher, join requests, role changes |
| Users | Platform-admin-only account administration |
| Live traffic | SSE feed |
| Audit | Keyset-paginated log |

**Real-time alerts.** `useAlertToasts` subscribes to `/api/alerts/stream`
once from `Layout.tsx` — so toasts survive navigation rather than only firing
while the Alerts page is open — and auto-dismisses after 8s.

**Connecting an API by key.** The Registry assumes you can produce a spec for
the API you want watched, which doesn't hold for a third-party API where all
you have is a key. **Connected APIs** covers that case: pick Anthropic,
OpenAI, Google Gemini or "custom", paste the key, and the endpoints for that
provider are merged into the same `known_endpoints` inventory a spec upload
would have produced (tagged `source="connection:<id>"`, so removing the
connection removes exactly those endpoints again). Optionally the key is
checked live against the provider with one read-only GET, and the result is
shown as the connection's status.

The key is encrypted at rest with Fernet — this is the only recoverable
secret the app stores, since probing requires replaying it upstream. Set
`ENCRYPTION_KEY` if you ever plan to rotate `SECRET_KEY`; without it the
encryption key is derived from `SECRET_KEY` and rotating that means every
saved provider key has to be re-entered. Responses only ever carry a masked
prefix + last 4. Custom targets are restricted to HTTPS hosts that resolve to
public addresses, so a connection can't be used to reach link-local metadata
services or the internal network.

**Onboarding.** Shown on the Dashboard only when an account has no
endpoints, no shadow endpoints, and no traffic. Three steps, each marked done
from the same `Stats` the Dashboard already polls; a "send demo traffic"
button posts two synthetic events (one deliberately undocumented) so the
detection loop is visible immediately. Dismissible and self-retiring.

**Accessibility and mobile.** The sidebar collapses below `md` into a
hamburger drawer with backdrop and auto-close on navigation. Icon-only
buttons carry `aria-label`s; interactive rows and cards have visible focus
rings. Shared components (`Badge`, `EmptyState`, `PageHeader`, `StatCard`)
support dark mode.

---

## Scaling and deployment

Setting `REDIS_URL` switches on three things at once
([ADR 003](docs/adr/003-redis-streams-ingest-queue.md),
[ADR 004](docs/adr/004-scheduler-leader-election.md)):

1. **Ingest queue.** `/api/ingest/*` publishes to a Redis Stream and returns;
   `app/worker.py` consumes via a consumer group. Failures retry up to 5
   times then move to `apimonitor:ingest:dead`. Messages left pending by a
   crashed consumer are reclaimed after 60s via `XAUTOCLAIM`.
2. **Distributed rate limiting.** slowapi switches to shared Redis storage.
3. **Scheduler leader election.** A Redis lock (`SET NX PX` + compare-and-set
   renewal) ensures the write-side jobs — retrain, prune, rollup, idle-scan —
   run on exactly one replica. The gauge-refresh job is deliberately *not*
   gated: Prometheus scrapes each replica's `/metrics` independently, so
   every replica must refresh its own in-process gauges.

Ingest becomes eventually-consistent when queued: an accepted event may not
be queryable for a moment.

### Single host

`docker-compose.prod.yml` is the production overlay for one machine: Caddy terminating
TLS on :80/:443 with automatic Let's Encrypt certificates, every other port rebound to
loopback, and `APP_ENV=production` with docs and demo routes off.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --no-build
```

[docs/deployment-oracle-free.md](docs/deployment-oracle-free.md) walks through a complete
free-tier deployment on an Oracle Cloud Always Free VM.

For a public demo with no cloud account and no payment card,
[docs/deployment-render.md](docs/deployment-render.md) runs the released image on
Render's free plan — single container on SQLite, no worker or observability
sidecars, sleeps when idle and resets storage on every deploy. Measured at
184 MiB against the free plan's 512 MB cap.
[docs/deployment-huggingface.md](docs/deployment-huggingface.md) covers the same
shape on a Hugging Face Space, which needs a PRO account.

### Kubernetes

`k8s/` holds plain manifests plus a `kustomization.yaml`
([ADR 005](docs/adr/005-kubernetes-manifests-and-observability-stack.md)
explains the choice over Helm):

```bash
kubectl create secret generic apimonitor-secrets \
  --from-literal=DATABASE_URL=mysql+pymysql://... \
  --from-literal=SECRET_KEY=$(openssl rand -base64 32) \
  --from-literal=MONITOR_API_KEY=$(openssl rand -base64 32) \
  --from-literal=ADMIN_PASSWORD=...

kubectl apply -k k8s/

kubectl delete job apimonitor-migrate --ignore-not-found
kubectl apply -f k8s/migrate-job.yaml
```

Includes web and worker Deployments, a Service, an HPA (CPU-targeted), and a
migration Job. `secret.example.yaml`, `ingress.example.yaml`, and
`migrate-job.yaml` are excluded from the kustomization on purpose — the first
two are templates, and Job specs are immutable so re-applying is a silent
no-op without deleting first.

The bundled `redis.yaml` is a convenience default with **no persistence**;
point `REDIS_URL` at managed Redis for anything beyond dev.

### CI/CD

`ci.yml` runs lint, type-check, backend tests (against a real MySQL service
container), frontend tests, and a security-scan job: `bandit` (blocking),
`pip-audit` and `safety` (informational), `npm audit` on production deps
(blocking), Semgrep, and Trivy on the built image (CRITICAL+fixed = blocking).

`cd.yml` builds and pushes to GHCR after CI passes on `main`, then runs
migrations and rolls out, gated behind a `production` GitHub Environment.

---

## Observability

### Metrics — `GET /metrics`

Restricted to internal networks by nginx; Prometheus authenticates with
`MONITOR_API_KEY`.

Key series: `apimonitor_open_alerts`, `active_alerts_total{severity}`,
`shadow_apis_detected_total`, `zombie_apis_total{status}`,
`apimonitor_events_ingested_total{gateway}`, `apimonitor_anomaly_events_total`,
`apimonitor_ml_last_retrain_timestamp`, `apimonitor_ingest_queue_depth`,
`apimonitor_ingest_queue_dead_letter_total`, and
`apimonitor_request_duration_seconds` (a Histogram — the older
`api_request_duration_seconds` is a Counter and can only yield an average).

### Alerting

`prometheus/alert_rules.yml` covers: too many open high-severity alerts, a
stalled ingest pipeline, ML retrain not succeeding for 2h, a growing queue
backlog or dead-letter stream, and p95 latency above threshold.

Alertmanager routes `severity=critical` to a faster-repeating receiver. The
receiver URL comes from `ALERT_WEBHOOK_URL`, defaulting to a local no-op sink
so the stack starts clean and alerts remain visible in the UI on :9093. Point
it at a Slack incoming webhook, PagerDuty, or an internal endpoint to be paged.

### Tracing

`app/tracing.py` instruments FastAPI and SQLAlchemy. Set
`OTEL_EXPORTER_OTLP_ENDPOINT` to export (bundled Jaeger listens on
`http://jaeger:4318`, UI on :16686). Unset, spans are created and dropped —
no connection-error noise without a collector.

### Logs

The `audit` logger emits one JSON line per security event to stdout:

```bash
docker compose logs -f web | grep '"audit":true'
```

Promtail ships all container logs to Loki, provisioned as a Grafana
datasource so logs are searchable next to metrics.

---

## Data retention and privacy

Full policy: [`docs/data-retention-policy.md`](docs/data-retention-policy.md).

- **Redaction before storage.** Query parameters named `token`, `password`,
  `api_key`, `auth`, `session`, `jwt`, `secret`, and similar have their
  *values* replaced with `REDACTED` before a `TrafficEvent` row is written —
  so redacted paths are what reach the database, ML scoring, and alert text.
  Request and response **bodies are never captured**.
- **Retention.** Raw `traffic_events` are kept 30 days, then aggregated into
  `traffic_daily_summary` and deleted. Refresh tokens are pruned once expired
  (or 30 days after revocation). Summaries and alerts are kept indefinitely.
- **Right to delete.** `DELETE /api/privacy/traffic-data` purges every
  captured event matching an IP and/or session id, in chunks, audit-logged.
  `traffic_events` is the only table carrying those identifiers, so this
  covers the full footprint.
- **Audit log is exempt** — deliberately. It records *who did what*,
  including deletion requests themselves; letting it be erased by the same
  action would destroy the evidence of that action.

### Backup and restore

The database is the only source of truth for the endpoint inventory, alert
history and the audit log. None of it can be reconstructed from traffic once
it is gone, and retention pruning is not a backup — it deletes.

```bash
./scripts/backup_db.sh backup                    # timestamped dump into ./backups
./scripts/backup_db.sh verify backups/<file>     # load it into a scratch DB and count rows
./scripts/backup_db.sh restore backups/<file>    # overwrite the live DB (prompts to confirm)
```

Works against both MySQL and SQLite, reading `DATABASE_URL` from the
environment or `.env`. Dumps land in `./backups`, which is gitignored — they
contain password hashes and the full audit log, so treat them as secrets and
store them off-host.

Two things worth doing rather than assuming:

- **Schedule `backup` and ship the output off the machine.** A dump on the
  same disk as the database does not survive the failure you are insuring
  against.
- **Run `verify` on a real dump periodically.** A backup nobody has restored
  is a hypothesis. `verify` loads the dump into a throwaway database and
  counts rows, so it can run against production dumps without touching
  production.

If a restored dump predates a schema change, run `alembic upgrade head`
afterwards.

### Starting a tenant from clean

An instance used for demos or e2e runs carries synthetic endpoints and alerts
that would show up as findings against a real organization's traffic.
`scripts/reset_data.py` clears operational data while keeping accounts and
organizations:

```bash
python scripts/reset_data.py --dry-run              # report what would go
python scripts/reset_data.py --yes                  # traffic, inventory, alerts, connections
python scripts/reset_data.py --yes --test-users --audit   # also e2e_* accounts and the audit log
```

---

## Testing

```bash
python -m pytest                 # backend (364 tests, SQLite in-memory)
cd frontend && npm test          # frontend unit/component (30 tests, vitest)
cd frontend && npm run test:e2e  # Playwright — needs a running backend
```

No MySQL is required for the backend suite. Redis-dependent tests use
`fakeredis` (with its `lua` extra for the leader-election scripts).

| Area | Files |
|---|---|
| Auth and sessions | `test_refresh_token_flow`, `test_login_lockout`, `test_password_reset`, `test_mfa`, `test_api_keys` |
| Multi-tenancy | `test_org_context`, `test_orgs`, `test_default_organization`, `test_org_data_isolation` |
| ML | `test_ml_versioning`, `test_ml_features`, `test_anomaly_edge_cases`, `test_anomaly_threshold` |
| Ingestion | `test_ingest_queue`, `test_registry_import_formats`, `test_traffic_pruning`, `test_schema_hardening` |
| Data layer | `test_traffic_trend`, `test_cursor_pagination`, `test_db_pool_settings` |
| Infrastructure | `test_leader_election`, `test_distributed_rate_limiting`, `test_tracing`, `test_alerts_stream` |
| Privacy and audit | `test_pii_redaction`, `test_traffic_deletion`, `test_audit_logging` |
| Config and secrets | `test_secrets_provider`, `test_secrets_dir`, `test_validation_errors`, `test_rate_limiting` |

**Playwright e2e** (`frontend/e2e/`) covers login, registration, logout, the
admin-only Users gate as both admin and viewer, and three CRUD flows (alert
acknowledge, shadow acknowledge, zombie retire). Requires a running backend
against a migrated database — see [`frontend/e2e/README.md`](frontend/e2e/README.md).

**Load testing** (`loadtest/`) — a Locust suite with measured baselines, plus
k6 scripts. See [`loadtest/README.md`](loadtest/README.md) for numbers and,
importantly, what they do and don't tell you.

---

## Project layout

```
app/
  main.py            FastAPI app, lifespan, middleware
  models.py          SQLAlchemy models
  config.py          Settings (env → .env → secrets manager → /run/secrets)
  deps.py            Auth and RBAC dependencies
  security.py        Hashing, JWT, TOTP, role enums
  tracing.py         OpenTelemetry setup
  worker.py          Redis Streams ingest consumer
  routers/           One module per resource
  services/          Business logic, ML, parsers, queue, leader election
  jobs/scheduler.py  Background jobs
alembic/             Migrations
frontend/            React SPA (src/, e2e/)
k8s/                 Kubernetes manifests + kustomization
loadtest/            Locust and k6 scripts
docs/adr/            Architecture decision records
tests/               Backend test suite
nginx/ prometheus/ alertmanager/ grafana/ loki/ promtail/   Infra config
```

### Architecture decision records

| ADR | Topic |
|---|---|
| [001](docs/adr/001-alembic-migration-strategy.md) | Alembic migration strategy |
| [002](docs/adr/002-multi-tenancy-schema.md) | Multi-tenancy schema and the two-axis role model |
| [003](docs/adr/003-redis-streams-ingest-queue.md) | Redis Streams for the ingest queue |
| [004](docs/adr/004-scheduler-leader-election.md) | Scheduler leader election |
| [005](docs/adr/005-kubernetes-manifests-and-observability-stack.md) | Plain K8s manifests; observability integration points |

---

## Known limitations

Consolidated so they're findable rather than scattered. These are deliberate
scope decisions or genuinely unverified areas — not unknown bugs.

**Unverified in the environment this was built in**

- **Kubernetes manifests have never been applied to a live cluster.**
  `kubectl kustomize k8s/` confirms they *render*; that is strictly weaker
  than confirming they *run*.
- **The CD workflow has never executed.** It needs a `production` GitHub
  Environment with required reviewers and a `KUBE_CONFIG_PRODUCTION` secret —
  repo-settings and cluster-access decisions a workflow file can't make for
  itself. `build-and-push` works standalone; `deploy-production` fails at the
  kubeconfig step until configured.
- **Load-test numbers were measured against SQLite, not MySQL**, in
  synchronous (unqueued) mode. They characterize SQLite's single-writer lock
  more than the application. Do not quote them as production figures — see
  [`loadtest/README.md`](loadtest/README.md).
- **The k6 scripts have never been run** (no k6 binary available). The Locust
  suite has.
- **Promtail's log shipping is untested on Docker Desktop.** It mounts
  `/var/lib/docker/containers`, which only exists on a native Linux Docker
  host. Use Loki's Docker driver plugin on Desktop, or a DaemonSet shipper in
  Kubernetes.

**Deliberately not implemented**

- **Table partitioning** for `traffic_events` / `audit_log`. MySQL
  `PARTITION BY RANGE` isn't expressible through Alembic's portable helpers
  (it needs raw `op.execute()`), and there was no live MySQL to verify
  partition-management DDL against. The pruning jobs already delete in
  bounded chunks to avoid long locks, so this is an optimization, not a
  correctness gap.
- **GraphQL introspection and gRPC/protobuf reflection** import. Both need
  materially different machinery than the three text-format parsers (a live
  call to a target service; binary descriptor parsing) and warrant their own
  pass.
- **Trace context does not propagate across the Redis queue.** The HTTP hop
  and the worker hop are each traced, but as separate traces. Closing this
  means injecting trace context into the message payload and extracting it on
  consume.
- **No email delivery** for password reset — tokens go to the application log.
- **Per-page dark-mode audit.** Shared components support dark mode; several
  individual pages still have hard-coded light-mode classes. A full WCAG
  contrast and screen-reader pass has not been done.
- **Playwright e2e is not wired into CI** — it needs a migrated database
  provisioned as a CI step, similar to `test-backend`'s MySQL service.
