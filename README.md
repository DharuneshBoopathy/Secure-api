# API Security Monitor

A runtime API governance platform that detects shadow APIs, zombie endpoints, and anomalous traffic patterns in real time. Ingests traffic from nginx JSON logs, batch HTTP event feeds, or raw PCAP files and scores every request with an ensemble ML anomaly detector.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Quick Start — Docker](#quick-start--docker)
- [Local Development Setup](#local-development-setup)
- [Environment Variables](#environment-variables)
- [Security Model](#security-model)
- [API Reference](#api-reference)
- [Observability](#observability)
- [Running Tests](#running-tests)

---

## Architecture Overview

```
                    ┌──────────────────────────────────────────────┐
                    │               nginx :80                       │
                    │  rate-limit 20 r/s · security headers        │
                    └───────────────────┬──────────────────────────┘
                                        │ proxy
                    ┌───────────────────▼──────────────────────────┐
                    │           FastAPI (uvicorn) :8000             │
                    │                                               │
                    │  ┌─────────────┐   ┌──────────────────────┐  │
                    │  │  Ingest     │   │  REST API + SPA      │  │
                    │  │  /batch     │──▶│  /api/*              │  │
                    │  │  /nginx-json│   │  /  (React SPA)      │  │
                    │  │  /pcap      │   └──────────────────────┘  │
                    │  └──────┬──────┘                             │
                    │         │                                     │
                    │  ┌──────▼──────────────────────────────────┐ │
                    │  │         Traffic Processor                │ │
                    │  │  path-normalise · shadow-detect         │ │
                    │  │  ML anomaly score · alert dedup         │ │
                    │  └──────┬──────────────────────────────────┘ │
                    │         │                                     │
                    │  ┌──────▼──────┐   ┌──────────────────────┐ │
                    │  │  MySQL 8.0  │   │    APScheduler       │ │
                    │  │  (ORM)      │   │  retrain · prune     │ │
                    │  └─────────────┘   │  idle-scan · metrics │ │
                    │                    └──────────────────────┘ │
                    └──────────────────────────────────────────────┘
                                        │ scrape /metrics
                    ┌───────────────────▼──────────────────────────┐
                    │         Prometheus :9090 → Grafana :3000      │
                    └──────────────────────────────────────────────┘
```

### Core components

| Component | Location | Role |
|---|---|---|
| **FastAPI app** | `app/main.py` | Entry point, router registration, lifespan hooks |
| **Traffic processor** | `app/services/traffic_processor.py` | Per-event normalisation, classification, ML scoring |
| **ML anomaly engine** | `app/services/ml_anomaly.py` | IsolationForest + LOF ensemble; 15-feature vector |
| **Discovery service** | `app/services/discovery_service.py` | Shadow/zombie classification, risk scoring |
| **Audit service** | `app/services/audit_service.py` | Dual-sink structured logging (MySQL + stdout JSON) |
| **Scheduler** | `app/jobs/scheduler.py` | Background jobs: retrain, prune, idle-scan, metrics |
| **Frontend SPA** | `frontend/src/` | React + Vite + Tailwind; built output served by FastAPI |

### Data flow

1. Traffic arrives via `/api/ingest/*` (nginx log line, event batch, or PCAP upload).
2. Each event is path-normalised (`/users/123` → `/users/{id}`), matched against registered OpenAPI endpoints, and scored by the ML model.
3. Undocumented endpoints are recorded as **shadow endpoints** with a risk score.
4. Endpoints with declining traffic are promoted through the **zombie lifecycle**: `ACTIVE → DECLINING → IDLE → ZOMBIE → DEAD`.
5. Anomalous events and lifecycle changes emit **deduplicated alerts** (6-hour suppression window).
6. A Prometheus gauge is refreshed every 2 minutes for Grafana dashboards.

---

## Quick Start — Docker

One command starts MySQL, the API, nginx, Prometheus, and Grafana:

```bash
# Option A: Makefile (GNU Make required)
make up

# Option B: Shell wrapper
./scripts/setup-dev-env.sh && docker compose up --build

# Option C: Manual
python scripts/setup_dev_env.py   # generates .env with secure random secrets
docker compose up --build
```

> **Note:** `setup_dev_env.py` is idempotent — it skips generation when `.env`
> already exists with every required secret, and auto-fills the file if any
> required value is missing.  Pass `--force` (or run `make reset-env`) to
> rotate every secret.

| Service | URL |
|---|---|
| API + SPA | http://localhost:8000 |
| nginx proxy | http://localhost:80 |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

On first boot the admin account is provisioned automatically. The generated password is printed **once** to the web container log:

```bash
docker compose logs web | grep "Initial Admin Password"
```

### Kubernetes / Docker Swarm — mounted file secrets

`SECRET_KEY`, `ADMIN_PASSWORD`, and `MONITOR_API_KEY` can be supplied as mounted files instead of environment variables. Create files at `/run/secrets/<VARIABLE_NAME_LOWERCASE>`:

```yaml
# docker-compose snippet with Docker secrets:
secrets:
  secret_key:
    file: ./secrets/secret_key.txt
services:
  web:
    secrets:
      - secret_key
    # omit SECRET_KEY env var entirely
```

The app reads `/run/secrets/secret_key`, `/run/secrets/admin_password`, and `/run/secrets/monitor_api_key` automatically. Resolution order: **environment variable → `.env` file → `/run/secrets/` file → built-in default**.

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for MySQL and the observability stack)

### Backend

```bash
# 1. Start MySQL, Prometheus, Grafana
docker compose up -d mysql prometheus grafana

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — DATABASE_URL must point to the local MySQL container

# 4. Start the API server (auto-reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 5. (Optional) Seed demo traffic
python scripts/seed_demo.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # dev server on :5173, proxies /api → :8000
npm run build    # production build into frontend/dist/ (served by FastAPI)
```

---

## Environment Variables

All variables are read by `app/config.py` (pydantic-settings). Resolution order per field: **environment variable → `.env` file → `/run/secrets/<name>` → built-in default**.

### Required in production

| Variable | Description |
|---|---|
| `DATABASE_URL` | SQLAlchemy connection string, e.g. `mysql+pymysql://user:pass@host/db` |
| `SECRET_KEY` | JWT signing key — **minimum 32 characters**, must not start with `change-me`. The app refuses to start if this is weak. |
| `MONITOR_API_KEY` | Static API key for non-JWT automation clients (`X-Monitor-Key` header). |
| `ADMIN_PASSWORD` | Bootstrap admin password. Auto-generated as a cryptographically random string if unset; printed once in the startup log. |
| `MYSQL_ROOT_PASSWORD` | MySQL root password (Docker Compose only). |
| `MYSQL_PASSWORD` | Password for the `apimonitor` DB user (Docker Compose only). |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin password (Docker Compose only). |

### Optional tuning

| Variable | Default | Description |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Username for the bootstrap admin account. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime. |
| `CORS_ORIGINS` | _(empty)_ | Comma-separated extra CORS origins for the browser UI. |
| `ML_RETRAIN_MINUTES` | `15` | Anomaly model retrain interval in minutes (minimum 5). |
| `ANOMALY_THRESHOLD` | `0.8` | Normalised score `[0.0–1.0]` above which an event is flagged anomalous. Raise to reduce false positives; lower to increase sensitivity. |
| `IDLE_THRESHOLD_HOURS` | `24` | Hours of silence before a documented endpoint is considered idle. |
| `ZOMBIE_WINDOW_DAYS` | `30` | Traffic lookback window for zombie classification. Raw traffic events older than this are also pruned. |
| `ZOMBIE_IDLE_THRESHOLD_DAYS` | `14` | Days without traffic before an endpoint enters IDLE state. |
| `ZOMBIE_DEAD_THRESHOLD_DAYS` | `30` | Days without traffic before an endpoint is promoted to DEAD. |
| `ZOMBIE_LOW_TRAFFIC_RPD` | `1.0` | Requests-per-day threshold below which traffic is considered "low". |

---

## Security Model

### Authentication

Every protected route accepts credentials in one of three forms (evaluated in priority order):

1. `Authorization: Bearer <access-JWT>` header
2. `X-Monitor-Key: <api-key>` header
3. `?auth=<jwt-or-api-key>` query parameter (for SSE streams and integrations that cannot set headers)

JWTs are signed with `SECRET_KEY` using HS256. Access tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES`. Refresh tokens embed a cryptographically random `jti` claim (RFC 7519 §4.1.7) that makes every token unique regardless of issue time, ensuring the rotation-based replay-protection mechanism always works correctly.

Refresh tokens are stored in MySQL as **SHA-256 hashes** — the plaintext JWT is never persisted. On every `/api/auth/refresh` call the consumed token row is immediately marked revoked and a new row is inserted. Logout unconditionally revokes the submitted token.

### Role-based access control

Three tiers with cumulative privileges:

| Role | Permissions |
|---|---|
| `viewer` | Read all monitoring data: alerts, shadow endpoints, zombies, traffic, inventory, anomalies |
| `editor` | Viewer + ingest traffic, acknowledge alerts/shadows, retire/reactivate zombies, upload OpenAPI specs |
| `admin` | Editor + user management (CRUD), audit log access |

### Password policy

Passwords must contain: minimum 8 characters, at least one uppercase letter, one lowercase letter, one digit, and one special character. Enforced at registration, self-service password change, and admin user creation. Hashed with **bcrypt** (direct library call — passlib 1.7.x is not used for hashing due to incompatibility with bcrypt 4.x).

The bootstrap admin account is automatically re-keyed if it is found holding the literal string `"admin"` as a password on startup.

### Input validation

All ingest and auth schemas enforce `extra="forbid"` (Pydantic v2) — unknown fields are rejected with HTTP 422. Critical string fields are length-bounded:

| Field | Limit |
|---|---|
| `path` / `uri` | max 1 024 characters |
| `client_ip` / `remote_addr` | max 64 characters |
| `username` | 3–128 characters, pattern `^[a-zA-Z0-9_\-\.]+$` |
| `email` | 5–256 characters |
| `reason` (acknowledge/retire actions) | 3–512 characters |
| `password` | 8–256 characters |

### Rate limiting

slowapi enforces per-IP limits at the application layer:

| Route group | Limit |
|---|---|
| `POST /api/auth/login` | 5 / minute |
| `POST /api/auth/register` | 3 / minute |
| `POST /api/auth/refresh` | 10 / minute |
| `PUT /api/auth/me/password` | 5 / minute |
| `POST /api/auth/users` (admin) | 10 / minute |
| `POST /api/ingest/*` | 500 / minute |
| `GET /api/inventory/*` | 120 / minute |
| `GET /api/audit` | 60 / minute |
| `GET /api/traffic/stream` | 30 / minute |

The nginx reverse proxy adds a second independent layer: **20 r/s** sustained with a burst allowance of 40 for all `/api/` paths.

### Audit logging

Every mutating auth action (login, register, token refresh, password change, user create/update/deactivate) writes an `AuditLog` database row **and** emits a structured JSON line to stdout simultaneously. Both sinks share the same timestamp so SIEM pipelines can correlate them without clock skew.

Stdout format (one JSON line per event):

```json
{
  "audit": true,
  "event_type": "login_attempt",
  "actor": "alice",
  "target": "auth/login",
  "ip": "10.0.0.1",
  "user_agent": "Mozilla/5.0 ...",
  "timestamp": "2024-01-15T12:34:56.789012",
  "success": true,
  "details": {}
}
```

The `audit` logger uses `propagate=False` and a `%(message)s`-only formatter so no log-framework metadata wraps the JSON line — the output is directly consumable by log aggregation pipelines (Loki, Elasticsearch, Splunk) reading Docker stdout streams.

### Security headers (nginx)

Applied to all responses:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

The `/metrics` endpoint is restricted to internal Docker networks by nginx and is never reachable from the public internet. Prometheus authenticates via the `MONITOR_API_KEY` passed as a query parameter (`params: auth: ["${MONITOR_API_KEY}"]`), which docker-compose injects into `prometheus.yml` at container start.

### ML model signing

The serialized anomaly-detection model stored in `ml_model_state.blob` is prefixed with an **HMAC-SHA256 signature** computed with `SECRET_KEY`. Any blob that fails the HMAC check is refused before it reaches `pickle.loads`, closing the arbitrary-code-execution surface even if an attacker gains write access to the model table. Rotating `SECRET_KEY` invalidates all existing models; the scheduler retrains on the next tick and re-signs automatically.

### Authorization header logging

Nginx maps `$http_authorization` to a boolean `$has_auth` flag (`true`/`false`) before writing the access log. **Raw JWTs and API keys are never logged.** See `nginx/nginx.conf:log_format apimonitor_json` — the `"auth_present"` field carries only the boolean.

### TLS / Production deployment

This application is designed to run **behind a TLS-terminating reverse proxy** or load balancer (e.g., AWS ALB, Cloudflare, Traefik, Caddy, or an nginx gateway with Let's Encrypt):

```
  Internet
     │
     ▼
  TLS termination (ALB / Cloudflare / Caddy / nginx + certbot)
     │  plaintext HTTP
     ▼
  nginx :80 (rate limiting + security headers)
     │
     ▼
  FastAPI :8000
```

**Key facts:**
- The FastAPI middleware already emits `Strict-Transport-Security: max-age=31536000; includeSubDomains` (HSTS) on every response.
- CORS origins should be set to your production domain via `CORS_ORIGINS=https://yourdomain.com`.
- The `?auth=` query parameter for SSE streams means TLS is essential to protect tokens in transit.

**Do not** expose port 8000 or port 80 directly to the public internet without TLS in front.

---

## API Reference

All routes are prefixed with `/api`. Interactive Swagger UI is available at `/docs`; ReDoc at `/redoc`.

### Authentication — `/api/auth`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/login` | public | Issue access + refresh token pair |
| `POST` | `/register` | public | Self-registration (creates `viewer` account) |
| `POST` | `/refresh` | public | Rotate refresh token, issue new pair |
| `POST` | `/logout` | public | Revoke refresh token |
| `GET` | `/me` | viewer | Return authenticated user's profile |
| `PUT` | `/me/password` | viewer | Change own password |
| `GET` | `/users` | admin | List all users |
| `POST` | `/users` | admin | Create user with explicit role |
| `GET` | `/users/{id}` | admin | Fetch user by ID |
| `PATCH` | `/users/{id}` | admin | Update role / email / active status |
| `DELETE` | `/users/{id}` | admin | Soft-deactivate user and revoke all tokens |

**Login example:**

```bash
TOKEN=$(curl -sX POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<password>"}' \
  | jq -r .access_token)
```

### Traffic Ingestion — `/api/ingest`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/batch` | editor | JSON array of `IngestBatchItem` events |
| `POST` | `/nginx-json` | editor | Single nginx `log_format apimonitor_json` line |
| `POST` | `/nginx-json-raw` | editor | Raw nginx JSON log line as plain request body |
| `POST` | `/pcap` | editor | Wireshark `.pcap` upload — cleartext HTTP only, max 50 MB |

**Batch ingest example:**

```bash
curl -X POST http://localhost:8000/api/ingest/batch \
  -H "X-Monitor-Key: <api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "method": "GET",
      "path": "/api/users/123",
      "status_code": 200,
      "latency_ms": 12.5,
      "client_ip": "10.0.0.1",
      "auth_present": true
    }]
  }'
```

### Inventory — `/api/inventory`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `/discovered` | viewer | All endpoints observed in traffic |
| `GET` | `/shadow` | viewer | Undocumented endpoints only |
| `GET` | `/idle` | viewer | Documented endpoints with no recent traffic |
| `GET` | `/stats` | viewer | Dashboard counters (events/hour, open alerts, etc.) |

### Shadow Endpoints — `/api/shadow`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | viewer | Shadow endpoints with risk scores and evidence |
| `POST` | `/{id}/acknowledge` | editor | Acknowledge with reason (body: `{"reason": "..."}`) |
| `POST` | `/{id}/add-to-registry` | editor | Promote shadow to registered OpenAPI endpoint |

Risk levels: `LOW` (read-only, < 10 hits) → `MEDIUM` → `HIGH` → `CRITICAL` (write methods with ≥ 10 hits).

### Zombie Endpoints — `/api/zombie`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | viewer | Zombie endpoint states with traffic metrics |
| `GET` | `/summary` | viewer | Lifecycle state counts |
| `POST` | `/{id}/retire` | editor | Mark endpoint as intentionally retired |
| `POST` | `/{id}/reactivate` | editor | Reset a retired endpoint to active |

Lifecycle: `ACTIVE → DECLINING → IDLE → ZOMBIE → DEAD`. Reactivation is only possible from `ZOMBIE` or `DEAD`.

### Alerts — `/api/alerts`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | viewer | List alerts; filter with `?acknowledged=false&severity=HIGH` |
| `POST` | `/{id}/ack` | editor | Acknowledge alert |

### Anomalies — `/api/anomalies`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | viewer | Traffic events scored above `ANOMALY_THRESHOLD` |

The ML engine uses an IsolationForest + LocalOutlierFactor ensemble. Features include: hour-of-day, day-of-week, status code, latency, body size, auth presence, path depth, HTTP method, whether the path is new, query parameter count, query string Shannon entropy, request size, and response size. A high `query_entropy` score is a strong signal for SQL injection or BOLA attack patterns.

### Live Traffic Stream — `/api/traffic`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `/stream` | viewer | Server-Sent Events — new events every 2 s, up to 25 per tick |

Pass credentials via `?auth=Bearer+<jwt>` or `?auth=<api-key>` for SSE clients that cannot set headers:

```javascript
const es = new EventSource('/api/traffic/stream?auth=' + apiKey);
es.onmessage = e => console.log(JSON.parse(e.data));
```

### OpenAPI Registry — `/api/registry`

| Method | Path | Min role | Description |
|---|---|---|---|
| `POST` | `/openapi` | editor | Upload OpenAPI spec (YAML) to define the documented endpoint set |
| `GET` | `/openapi/latest` | viewer | Retrieve the most recently uploaded spec |

Uploading a spec registers all paths as "known endpoints". Traffic to paths not in the spec is classified as shadow traffic.

### Audit Log — `/api/audit`

| Method | Path | Min role | Description |
|---|---|---|---|
| `GET` | `` | admin | Keyset-paginated audit log |

Uses cursor-based pagination — no `OFFSET` scan. Pass `?cursor_id=<next_cursor_id>` from the previous response to fetch the next page. `next_cursor_id` is `null` on the last page.

```bash
# First page (newest first)
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/audit?limit=25"
# → {"items": [...], "next_cursor_id": 4750}

# Next page
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/audit?cursor_id=4750&limit=25"
```

Filters: `?event_type=login_attempt`, `?from_ts=2024-01-01T00:00:00`, `?to_ts=2024-12-31T23:59:59`.

---

## Observability

### Prometheus metrics (`GET /metrics`)

Exposed by FastAPI, restricted to `127.0.0.1` by nginx. Scraped by the bundled Prometheus container every 15 s.

Key gauges: `apimonitor_open_alerts`, `apimonitor_shadow_endpoints`, `apimonitor_zombie_endpoints`, `apimonitor_events_last_hour`, `apimonitor_known_endpoints`.

### Grafana dashboards

Pre-provisioned dashboards are loaded from `grafana/dashboards/` on startup. Access at http://localhost:3000. Login with the `GRAFANA_ADMIN_PASSWORD` value from `.env`.

### Structured audit log

The `audit` Python logger emits one JSON line per security event to container stdout. In Docker:

```bash
docker compose logs -f web | grep '"audit":true'
```

In Kubernetes, stdout is captured by the node log driver and forwarded to your log aggregation pipeline.

---

## Running Tests

The full test suite uses SQLite in-memory databases — no running MySQL instance is required.

```bash
# Full suite with coverage enforcement
python -m pytest

# Single file without coverage threshold
python -m pytest tests/test_refresh_token_flow.py -v --no-cov

# Filter by test name
python -m pytest -k "test_replay_attack or test_anomaly" -v --no-cov
```

### Test coverage areas

| File | What it tests |
|---|---|
| `test_refresh_token_flow.py` | Token rotation, replay-attack prevention, logout, expired/revoked token rejection |
| `test_rate_limiting_integration.py` | 429 response format, per-IP quota, limit value verification |
| `test_validation_errors.py` | Pydantic schema boundaries for all auth and action schemas |
| `test_anomaly_edge_cases.py` | Score range, degenerate inputs, feature capping, `train_from_db` boundary |
| `test_ml_features.py` | Feature extraction: entropy, query param count, size fields |
| `test_schema_hardening.py` | `extra="forbid"`, path/IP length constraints on ingest schemas |
| `test_audit_logging.py` | Dual-sink (DB + stdout JSON) correctness and timestamp consistency |
| `test_cursor_pagination.py` | Keyset pagination walk, no-offset verification, composite index declaration |
| `test_traffic_pruning.py` | Chunked stale traffic deletion, age cutoffs |
| `test_secrets_dir.py` | `/run/secrets/` file loading, env var precedence, missing dir graceful handling |
| `test_anomaly_threshold.py` | `ANOMALY_THRESHOLD` env var override, boundary conditions |
