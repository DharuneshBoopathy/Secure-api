# Data retention policy

Formalizes what Phase 1's PII-handling work started (query-param redaction
+ the `DELETE /api/privacy/traffic-data` action) into a written policy:
what's stored, for how long, how it's redacted, and how to purge it early
for a GDPR/CCPA-style request. Written against the schema in `app/models.py`
as of this document's date — re-check against the actual models before
relying on it for a real compliance review, since schemas drift.

## What's captured, and what isn't

| Data | Table | Contains PII? | Redaction |
|---|---|---|---|
| Captured request metadata | `traffic_events` | `client_ip`, `session_id`, `user_agent`, and query-string values (until redacted) | Query params named `token`, `password`, `api_key`, `auth`, `session`, `jwt`, and similar are replaced with `REDACTED` **before the row is ever written** — see `app.services.pathutil.redact_sensitive_query_params`, applied in `app.services.traffic_processor.process_single_event`. Request/response **bodies** are never captured at all — only method, path, status, timing, and size. |
| Aggregated daily rollups | `traffic_daily_summary` | No — counts and averages only, no `client_ip`/`session_id`/path values tied to a specific request | N/A |
| Alerts | `alerts` | Redacted `path`/`detail` text only (inherits `traffic_events`' redaction — an alert is never built from a pre-redaction path) | N/A |
| Audit log | `audit_log` | `actor` (username), `ip`, `user_agent` of the person taking an administrative action (login, alert ack, org membership change, etc.) — **not** end-user traffic | N/A — this is an admin-action log, not captured traffic, and is exempt from the traffic retention/deletion rules below (see "Audit log exemption") |
| ML model state | `ml_model_state` | No — serialized sklearn estimators + per-feature mean/std, no raw request data | N/A |
| User accounts | `users` | Username, password hash (bcrypt), TOTP secret (if MFA enabled) — data the account holder provided directly, not captured traffic | N/A |

## Retention periods

| Data | Retention | Mechanism |
|---|---|---|
| `traffic_events` (raw) | `zombie_window_days` (default 30) from ingestion, **or** `keep_days=30` in the daily rollup job — whichever job runs first prunes it | `app.jobs.scheduler._prune_stale_traffic` (age-based hard delete) and `_traffic_rollup` → `aggregate_and_prune_old_traffic` (aggregates into `traffic_daily_summary`, then deletes the raw rows). Both leader-gated (see `app/services/leader.py`) so they run exactly once cluster-wide. |
| `traffic_daily_summary` | Indefinite | No pruning job exists for this table — it's already aggregated/anonymized (no per-request PII), so the cost of keeping it is low and the value (long-term trend dashboards) doesn't have an obvious expiry. Revisit if this table's growth becomes a real storage concern. |
| `alerts` | Indefinite | No pruning job. Acknowledged alerts and their `feedback` label (see `app/services/ml_anomaly.py`'s retrain loop) are historical signal for the ML model and for security review ("did we see this before"); deleting them would both lose that context and let the retrain loop re-learn from an attack it already correctly flagged once. |
| `audit_log` | Indefinite (see exemption below) | None — deliberate. |
| `refresh_tokens` | Expired, or revoked + 30 days | `app.jobs.scheduler._prune_expired_refresh_tokens`, leader-gated. |
| `ml_model_state` | Last 5 versions per org | `app.services.ml_anomaly._prune_old_versions` — see the model-versioning/rollback feature. |

### Audit log exemption

`audit_log` is **not** covered by the deletion action below and has no
retention/pruning job, by design: it is the record of *who did what*
(logins, alert acknowledgements, org membership changes, right-to-delete
actions themselves), which is exactly the kind of record that security and
compliance reviews (including GDPR's own accountability principle) expect
to survive a data-subject deletion request — otherwise a bad actor could
delete their own traffic data specifically to also erase the log entry
showing they deleted it. If your jurisdiction requires a hard cap on audit
log retention, add a time-based archival/deletion job explicitly — do not
fold it into the traffic-deletion action.

## Right-to-delete: `DELETE /api/privacy/traffic-data`

Admin-only, rate-limited (`10/minute`), audit-logged as
`traffic_data_deleted`. Accepts `client_ip` and/or `session_id`; deletes
every matching `traffic_events` row via
`app.services.traffic_processor.delete_traffic_for_client` (chunked,
5000 rows/commit, to avoid a single giant transaction on a large table).

**Scope check**: `traffic_events` is the only table in the schema with a
`client_ip` or `session_id` column (verified against `app/models.py`), so
this action already covers everywhere raw per-request identifiers live —
there is nothing else to cascade the deletion into. `traffic_daily_summary`
and `alerts` retain redacted/aggregated data that isn't keyed by
`client_ip`/`session_id` and isn't itself PII (see the table above), so
they're correctly out of scope for this action rather than a gap.

**Not covered, and why**: a registered `User`'s own account data (username,
password hash) is separate from captured traffic and has its own admin
lifecycle (`DELETE /api/auth/users/{id}` deactivates/removes the account) —
this document is about *captured traffic*, not user-account erasure.
