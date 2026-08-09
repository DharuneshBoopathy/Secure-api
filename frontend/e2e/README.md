# Playwright e2e tests

Run against a real backend and frontend — no mocking. Playwright's
`webServer` config only owns the frontend dev server's lifecycle
(`npm run dev`); the backend is your responsibility to have running first,
since it needs a migrated database.

## One-time setup

```bash
# From the repo root — creates a throwaway SQLite DB and runs migrations
# against it. The schema is dialect-portable (openapi_snapshots.raw_yaml uses
# with_variant so it renders LONGTEXT on MySQL and TEXT elsewhere), so this
# needs no special handling.
DATABASE_URL=sqlite:///./e2e.db \
SECRET_KEY=e2e-test-secret-key-minimum-32-characters-long \
MONITOR_API_KEY=e2e-test-monitor-key-minimum-32-characters \
ADMIN_PASSWORD=E2eAdminPass123! APP_ENV=development \
python -m alembic upgrade head
```

## Running

```bash
# Terminal 1, from the repo root — the backend, pointed at e2e.db:
DATABASE_URL=sqlite:///./e2e.db \
SECRET_KEY=e2e-test-secret-key-minimum-32-characters-long \
MONITOR_API_KEY=e2e-test-monitor-key-minimum-32-characters \
ADMIN_PASSWORD=E2eAdminPass123! \
APP_ENV=development \
CORS_ORIGINS=http://localhost:5173 \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2, from frontend/ — installs the browser once, then runs the suite
# (Playwright's webServer config starts `npm run dev` for you):
npx playwright install chromium
npx playwright test
```

Environment variables, all defaulting to the values in the setup snippet
above — override them if your backend uses different ones:

| Variable | Used by | Default |
|---|---|---|
| `E2E_BASE_URL` | all specs | `http://localhost:5173` |
| `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD` | `global-setup.ts`, `auth.spec.ts` | `admin` / `E2eAdminPass123!` |
| `E2E_MONITOR_API_KEY` | `core-flows.spec.ts` (seeds traffic via the API) | the key above |
| `E2E_DB_PATH` | `core-flows.spec.ts` (zombie seeding) | `../../e2e.db` |
| `E2E_PYTHON` | `core-flows.spec.ts` | `python` |

To run against an already-running local dev instance instead of a dedicated
e2e stack, point `E2E_BASE_URL` and `E2E_DB_PATH` at it — e.g.
`E2E_BASE_URL=http://127.0.0.1:8000 E2E_DB_PATH=../apimonitor.db`.

**Re-running within the same minute**: `POST /api/auth/login` and
`/register` are rate-limited (5/min and 3/min — see the README's Rate
limiting section), and slowapi's in-memory counters live in the backend
process, not the test run — they persist across consecutive
`npx playwright test` invocations against the same long-lived backend.
Running the full suite twice back-to-back can 429 on the second run's
login/register calls (this was hit and confirmed while writing these
tests, not theoretical). Wait ~60s between runs, or restart the backend
process, if you see login/register tests fail only on a repeat run.

## What's covered

- `auth.spec.ts` — login (valid + invalid credentials), registration, logout.
- `role-gated-nav.spec.ts` — the platform-admin-only Users page: an admin
  sees it, a freshly-registered viewer sees "Admin access required" instead.
- `core-flows.spec.ts` — three CRUD flows against real data:
  - alert acknowledge (ingests one undocumented request via the API, which
    synchronously produces an alert — see app/services/traffic_processor.py
    — then acknowledges it in the UI)
  - shadow endpoint acknowledge (same ingest-then-act-in-UI shape)
  - zombie endpoint retire — this one seeds a `zombie_endpoint_state` row
    directly into the SQLite DB via `seed_zombie.py` first, because zombie
    state is normally computed by a 30-minute-interval background job
    (`app/jobs/scheduler.py::_idle_scan`), far too slow for a test timeout.
    Ingest, by contrast, produces shadow endpoints and alerts *synchronously*
    in-request, so those two flows don't need this kind of seeding.

## What isn't covered here

Onboarding wizard, request-detail drawers, and toast notifications are
covered by the vitest unit/component tests instead (`OnboardingWizard.test.tsx`,
`Drawer.test.tsx`, `Alerts.test.tsx`, `Anomalies.test.tsx`,
`useAlertToasts.test.tsx`) — they don't need a real backend and run in CI
today, unlike this e2e suite (see the root README's CI section: this suite
is not currently wired into `.github/workflows/ci.yml`, since doing so
would need a migrated test database provisioned as a CI step, similar to
`test-backend`'s MySQL service container).
