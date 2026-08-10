---
title: API Security Monitor
emoji: 🛡️
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 8000
pinned: false
license: mit
---

# API Security Monitor

Runtime API governance: ingests traffic, builds a live inventory of every
endpoint actually being called, flags **shadow APIs** (serving traffic but
absent from the spec) and **zombie APIs** (documented but no longer used), and
scores requests with a per-organization anomaly detector that explains why it
flagged something.

Source: <https://github.com/DharuneshBoopathy/Secure-api>

## About this deployment

This Space runs the released container from GHCR, unchanged apart from the
platform settings in the `Dockerfile`. It is a **demo instance**:

- **Storage is ephemeral.** The SQLite database lives in `/tmp` and is wiped
  whenever the Space restarts or rebuilds. Sign in, ingest some traffic, watch
  the inventory and alerts populate — but treat everything as disposable.
- **Single container.** No Redis, no separate worker, no Prometheus/Grafana.
  Ingestion runs inline in the request instead of through the queue, and the
  scheduler runs in-process. Both are supported modes, not degradations.
- **Free CPU tier**, so it sleeps after a stretch of inactivity and takes a
  moment to wake.

The full stack — worker, Redis queue, Prometheus, Grafana, Loki, Jaeger, and
TLS via Caddy — is in `docker-compose.yml` in the repository.

## Required secrets

Set these under **Settings → Variables and secrets** before the Space will
start. Production validation refuses to boot without them, on purpose.

| Secret | Notes |
|---|---|
| `SECRET_KEY` | 32+ random chars. Signs JWTs and derives the credential-encryption key |
| `MONITOR_API_KEY` | 32+ random chars. The `X-Monitor-Key` used by ingestion clients |
| `ADMIN_USERNAME` | Bootstrap admin — pick something other than `admin` |
| `ADMIN_PASSWORD` | Strong; this instance is public |

Generate them with:

```bash
openssl rand -base64 36 | tr -d '/+=' | head -c 48
```

Optionally set `PUBLIC_BASE_URL` and `CORS_ORIGINS` to the Space URL
(`https://<user>-<space>.hf.space`) — the UI and API share an origin here, so
neither is required.
