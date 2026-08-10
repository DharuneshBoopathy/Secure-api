"""Seeds one ZombieEndpointState row directly into the e2e SQLite DB.

Only exists because zombie state is normally computed by a scheduled
background job (app/jobs/scheduler.py::_idle_scan, every 30 minutes) — far
too slow for an e2e test's timeout. Ingested traffic, by contrast, produces
shadow endpoints and alerts synchronously (see process_single_event), so
those flows don't need this kind of seeding; only the zombie-retire flow
does. Run via `E2E_DB_PATH=<path-to-db> python e2e/seed_zombie.py`.
"""

import os
import sqlite3
from datetime import UTC, datetime

# The database location comes from the environment, not argv. A connection
# target taken straight off the command line is trivially redirected by
# whatever invokes the script, and this one opens a database and deletes rows
# from it. core-flows.spec.ts sets E2E_DB_PATH when it shells out.
db_path = os.environ.get("E2E_DB_PATH", "../e2e.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()
org_id = cur.execute("SELECT id FROM organizations ORDER BY id LIMIT 1").fetchone()[0]
now = datetime.now(UTC).isoformat()

# Idempotent — re-running against the same e2e.db (e.g. a second local test
# run without recreating the DB) would otherwise hit the UNIQUE constraint
# on (org_id, method, path_template) from the previous run's row.
cur.execute(
    "DELETE FROM zombie_endpoint_state WHERE org_id = ? AND method = 'GET' AND path_template = '/api/legacy/report'",
    (org_id,),
)

cur.execute(
    """
    INSERT INTO zombie_endpoint_state
        (org_id, method, path_template, last_request_at, requests_7d, requests_14d,
         requests_30d, avg_daily_requests_30d, status, risk_level, retired)
    VALUES (?, 'GET', '/api/legacy/report', ?, 0, 0, 1, 0.03, 'ZOMBIE', 'MEDIUM', 0)
    """,
    (org_id, now),
)
conn.commit()
print(f"seeded 1 zombie row for org_id={org_id}")
