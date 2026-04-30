# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend

```bash
# Start infrastructure (MySQL, Prometheus, Grafana)
docker compose up -d

# Install dependencies
pip install -r requirements.txt

# Run API server (dev)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Run tests
python -m pytest

# Seed demo data (requires running server)
python scripts/seed_demo.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # dev server on :5173
npm run build      # build to frontend/dist/ (served by FastAPI in prod)
npm run test       # run Vitest tests
```

### Docker (full stack)

```bash
# Full production-like stack (MySQL + API + built-in UI)
docker compose -f docker-compose.yml -f docker-compose.app.yml up --build
# Open http://localhost:8000
```

## Architecture

This is an **API Security Monitor** — a runtime API governance platform that detects shadow APIs, zombie endpoints, and anomalous traffic patterns.

### Backend (FastAPI + MySQL)

**Entry point**: `app/main.py` — registers all routers under `/api`, mounts the Vite SPA from `frontend/dist/`, starts APScheduler background jobs, and applies security headers middleware.

**Configuration**: `app/config.py` uses `pydantic-settings` with `.env` file support. Key env vars:
- `DATABASE_URL` — MySQL connection string
- `MONITOR_API_KEY` — API key for non-JWT automation clients
- `SECRET_KEY` — JWT signing key (min 32 chars)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` — bootstrap admin credentials

**Data models** (`app/models.py`): SQLAlchemy ORM. Core tables:
- `traffic_events` — raw HTTP request log with anomaly scores
- `known_endpoints` — registered OpenAPI endpoints (the "documented" set)
- `discovered_endpoints` — all observed endpoints from live traffic
- `shadow_endpoints` — undocumented endpoints receiving traffic
- `zombie_endpoint_state` — lifecycle status (ACTIVE → DECLINING → IDLE → ZOMBIE → DEAD)
- `alerts` — de-duplicated security alerts (6h dedup window for most types)
- `ml_model_state` — serialized IsolationForest + LOF model (pickle blob in DB)

**Authentication** (`app/deps.py`, `app/security.py`):
- Three-tier RBAC: `admin > editor > viewer`
- Accepts `Authorization: Bearer <JWT>`, `X-Monitor-Key` header, or `?auth=` query param
- Use `require_role(Role.EDITOR)` / `require_admin` / `require_viewer` as FastAPI dependencies on routes
- `verify_monitor_key` is a legacy wrapper kept for backward compatibility — new routes should use `require_role()`

**Traffic ingestion** (`app/routers/ingest.py` → `app/services/traffic_processor.py`):
- `POST /api/ingest/batch` — JSON batch of events
- `POST /api/ingest/nginx-json` — single nginx JSON log line
- `POST /api/ingest/pcap` — Wireshark `.pcap` upload (cleartext HTTP only, max 50MB)
- Each event is scored by the ML model, classified as documented/shadow, and triggers alerts

**ML anomaly detection** (`app/services/ml_anomaly.py`):
- Ensemble of IsolationForest + LocalOutlierFactor (sklearn)
- Features: hour, day-of-week, status code, latency, body size, auth presence, path depth, method
- Model trained from last 168h of traffic, retrained on a configurable interval (default 15 min, min 5 min)
- Model persisted as a pickle blob in `ml_model_state` table — loaded on each event batch
- Anomaly threshold: normalized score ≥ 0.8

**Discovery** (`app/services/discovery_service.py`):
- Path normalization in `app/services/pathutil.py` collapses numeric/UUID path segments for grouping
- Shadow risk scoring: write methods (POST/PUT/PATCH/DELETE) with ≥10 hits → CRITICAL
- Zombie classification uses a 30-day traffic window with configurable thresholds (`zombie_*` settings)

**Background jobs** (`app/jobs/scheduler.py`):
- ML retrain: configurable interval (default 15 min)
- Idle scan + zombie recompute: every 30 min
- Prometheus gauge refresh: every 2 min
- Traffic rollup + pruning (raw → `traffic_daily_summary`): every 24h, keeps 30 days raw

**Metrics**: `app/services/metrics.py` exposes Prometheus metrics at `/metrics`. Grafana is pre-provisioned via `grafana/provisioning/`.

### Frontend (React + Vite + Tailwind)

SPA at `frontend/src/`. Pages map to monitoring features: Dashboard, Shadow, Zombie, Alerts, Anomalies, Traffic, Registry (OpenAPI specs), Discovered, Idle, Audit, Login/Register.

In development, Vite dev server at `:5173` proxies `/api` to `:8000`. In production, the built `frontend/dist/` is served directly by FastAPI's SPA fallback route.

The `X-Monitor-Key` / JWT token is stored in `localStorage` and injected as a header by the API client (`frontend/src/api/client.ts`). Settings page lets users configure the key.

### Key design patterns

- **No Alembic**: Schema migrations are handled inline by `ensure_phase1_schema()` in `app/database.py` via `ALTER TABLE` DDL — appropriate for local/prototype use.
- **Alert deduplication**: `app/services/alerts_util.py::recent_duplicate()` prevents alert storms by checking for unacknowledged alerts of the same type/path within a configurable time window.
- **Path normalization**: `app/services/pathutil.py` normalizes paths like `/users/123` → `/users/{id}` for grouping traffic against OpenAPI templates.
