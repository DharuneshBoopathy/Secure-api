# 002 — Multi-tenancy schema shape

## Context

The original product spec (see the master prompt's decision checkpoint):
admin / user / viewer roles, where a "user" account owns an organization,
registers its APIs, and approves viewer requests into editor access. The
codebase as of Phase 1 implements a flat, single-tenant `viewer < editor <
admin` model with no organization boundary anywhere — `admin` already means
"can manage all users and read the full audit log," which is a *platform*
concern, not an org-scoped one.

Path B (true multi-tenant SaaS) was chosen. This is a real schema
migration touching `Organization`, a new membership table, `org_id` on
eight existing tables, and every router that reads/writes them.

## Decision

**Two independent role axes, not one collapsed model:**

1. **Platform role** — `User.role` (`admin` / `editor` / `viewer`), unchanged
   from Phase 1. Still governs the endpoints that are inherently
   cross-tenant by nature: `/auth/users` CRUD, `/auth/api-keys`,
   `/auth/mfa/*`, `/audit` (the full platform audit log), and
   `/privacy/traffic-data`. A platform `admin` is a superuser across every
   organization — think "the vendor's own ops team," not a tenant.
2. **Org role** — `OrgMembership.role` (`owner` > `editor` > `viewer`),
   scoped to one `(user_id, org_id)` pair, with `status`
   (`pending`/`active`/`revoked`) so the "viewer requests → owner approves"
   flow from the original spec has somewhere to live. This governs every
   org-scoped resource: traffic, alerts, shadow/zombie endpoints,
   anomalies, inventory, the OpenAPI registry, and ingest.

Rejected alternative: collapsing everything into one role enum (e.g.
`org_admin`/`org_editor`/`org_viewer`) and dropping the platform tier
entirely. Rejected because Phase 1 already built and tested five endpoints
(user CRUD, MFA, API keys, audit log, privacy deletion) against
`require_role(Role.ADMIN)` as a *platform* concept — collapsing the roles
would mean either exposing full user/API-key/audit management per-org
(wrong: a tenant shouldn't manage other tenants' users) or rewriting all
five endpoints and their tests for no behavioral gain.

**Tables** (`app/models.py`):

- `Organization(id, name, slug, owner_user_id, created_at)`. `owner_user_id`
  is a denormalized pointer to the current primary owner for fast display
  (org switcher, member lists); `OrgMembership` rows remain the source of
  truth for access control.
- `OrgMembership(id, user_id, org_id, role, status, created_at, decided_at)`,
  unique on `(user_id, org_id)`. `status="pending"` rows have no access
  until an owner approves them (`status="active"`); `"revoked"` rows are
  kept (not deleted) for audit history.

**org_id placement:** added to `KnownEndpoint`, `TrafficEvent`,
`DiscoveredEndpoint`, `Alert`, `OpenAPISnapshot`, `ShadowEndpoint`,
`ZombieEndpointState`, `TrafficDailySummary` — every table the master
prompt's Phase 2 spec lists, matching what's actually queried per-org.
`AuditLog` deliberately does **not** get `org_id`: it's already
platform-admin-only, and cross-org admin access is itself audit-logged
*into* this table, so scoping it by org would hide the exact events it
exists to record. `ApiKey` also gets `org_id` (not in the original list,
but necessary: an issued key ingests traffic into a specific org, so it
needs to carry which one).

**Org resolution per request:** `X-Org-Id` header, mirroring the existing
`X-Monitor-Key` header pattern (`app/deps.py`). If omitted and the caller
has exactly one active membership, that membership is used — this is what
keeps every existing Phase 1 test and automation client working unchanged
post-migration, since a freshly migrated single-tenant deployment has
exactly one org and one membership per user. If omitted and the caller has
zero or multiple memberships, the request is rejected (400) rather than
silently guessing which org to write into.

**Platform-admin cross-org access:** if `X-Org-Id` names an org the caller
has no active membership in, a platform `admin` is allowed through anyway
(support/audit access) — and that access is itself audit-logged
(`event_type="cross_org_access"`), per the master prompt's explicit
requirement that this path not be silent.

**Backfill:** a migration creates one `Organization` ("Default
Organization") and gives every existing platform-admin `User` row an
`owner` `OrgMembership` in it (bootstrap parity with `ensure_default_admin`
— see `ensure_default_organization` in `app/routers/auth.py`); a second
migration backfills `org_id = <default org id>` on all eight tables, then
a third makes the column `NOT NULL`. Three-step (nullable → backfill →
not-null) so the migration is safe to run against a populated production
table without a maintenance-window-length single transaction.

## Consequences

- Every org-scoped router needs an org-context dependency
  (`app/deps.py::get_org_context` / `require_org_role`) and every
  query/insert in those routers needs to filter/stamp `org_id`. This is the
  bulk of the Phase 2 diff.
- `TrafficEvent` ingestion (`app/services/traffic_processor.py`) and
  discovery/shadow/zombie bookkeeping (`app/services/discovery_service.py`)
  now take `org_id` as a required parameter — every row they create must be
  attributed to an org.
- The frontend needs an org switcher and a Members page (Phase 2 item 5) —
  tracked as a separate, explicitly deferred follow-up if not completed in
  the same pass as the backend changes.
- `MONITOR_API_KEY` (the legacy static key, still supported per Phase 1)
  maps to the system admin account, which — post-migration — has an
  `owner` membership in the Default Organization. Requests using the
  legacy key therefore default to the Default Organization exactly like
  any other single-membership caller, with no special-casing needed.

## Follow-up: what got scoped and what's deliberately deferred

Everything reachable through the API surface is org-scoped: `app/routers/{ingest,inventory,alerts,shadow,zombie,anomalies,traffic,openapi_registry}.py`, the `app/services/discovery_service.py` upsert/read functions, `app/services/alerts_util.py::recent_duplicate`, and `app/services/traffic_processor.py::process_single_event` / `aggregate_and_prune_old_traffic`. The scheduler's idle/zombie recompute job (`app/jobs/scheduler.py::_idle_scan`) now loops every `Organization` rather than running once globally — without that, org A's `KnownEndpoint` templates would match against org B's `TrafficEvent` rows for the same path template, corrupting both orgs' zombie/idle state. This is verified end-to-end in `tests/test_org_data_isolation.py`.

One thing is **deliberately not** org-scoped, and this is a scope decision, not an oversight:

- **Prometheus gauges** (`update_prometheus_gauges`) stay global/aggregate. `/metrics` is ops/infra-facing (network-restricted, not part of the tenant-facing read API), so aggregate counts across all orgs are the expected behavior for that audience, not a leak.

**Update (Phase 4)**: the ML anomaly model gap noted above at the time of writing this ADR has since been closed — `MLModelState` gained an `org_id` column (migration `dbe6fa71ee42`) and `app/services/ml_anomaly.py::train_from_db` now trains one model per org, with a further per-`(method, path template)` baseline for endpoints with enough volume. See the README's [Anomalies](../../README.md#anomalies--apianomalies) section for the current behavior; this paragraph is left in place as the historical record of why it was originally deferred.
