"""Clear operational and test data, keeping accounts and organizations.

Onboarding a real organization onto an instance that has been used for demos
or e2e runs means starting from an empty inventory — otherwise synthetic
shadow endpoints and alerts show up as findings against their traffic.

Deletes: traffic events and their derived inventory (discovered / shadow /
zombie / daily rollups), alerts, registered endpoints, key-based connections
and archived specs. Optionally also the e2e test accounts and the audit log.

Keeps by default: users, organizations, memberships and API keys — those are
access control, not sample data.

    python scripts/reset_data.py --dry-run
    python scripts/reset_data.py --yes
    python scripts/reset_data.py --yes --test-users --audit
"""

from __future__ import annotations

import argparse
import pathlib
import sys

# Run as `python scripts/reset_data.py` from the repo root without needing the
# package installed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, func, select  # noqa: E402

# Import the models package so every table is registered on Base.metadata.
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Alert,
    ApiKey,
    AuditLog,
    DiscoveredEndpoint,
    KnownEndpoint,
    MLModelState,
    MonitoredApi,
    OpenAPISnapshot,
    ShadowEndpoint,
    TrafficDailySummary,
    TrafficEvent,
    User,
    ZombieEndpointState,
)

# Operational data: everything derived from observed traffic or onboarding.
# Ordered so the tables a human is most likely to check appear first.
OPERATIONAL = [
    ("traffic_events", TrafficEvent),
    ("traffic_daily_summary", TrafficDailySummary),
    ("discovered_endpoints", DiscoveredEndpoint),
    ("shadow_endpoints", ShadowEndpoint),
    ("zombie_endpoint_state", ZombieEndpointState),
    ("alerts", Alert),
    ("known_endpoints", KnownEndpoint),
    ("monitored_apis", MonitoredApi),
    ("openapi_snapshots", OpenAPISnapshot),
    ("ml_model_state", MLModelState),
]

TEST_USERNAME_PREFIX = "e2e_"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually delete (otherwise dry-run)")
    parser.add_argument("--dry-run", action="store_true", help="report counts and exit (default)")
    parser.add_argument(
        "--test-users",
        action="store_true",
        help=f"also delete accounts named {TEST_USERNAME_PREFIX}* left behind by e2e runs",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="also clear the audit log (it is append-only evidence — only do this on a pre-production instance)",
    )
    parser.add_argument("--api-keys", action="store_true", help="also revoke and delete issued API keys")
    args = parser.parse_args()

    commit = args.yes and not args.dry_run

    session = SessionLocal()
    try:
        planned: list[tuple[str, int]] = []
        for label, model in OPERATIONAL:
            planned.append((label, session.scalar(select(func.count()).select_from(model)) or 0))

        if args.test_users:
            n = session.scalar(
                select(func.count()).select_from(User).where(User.username.like(f"{TEST_USERNAME_PREFIX}%"))
            )
            planned.append((f"users ({TEST_USERNAME_PREFIX}*)", n or 0))
        if args.audit:
            planned.append(("audit_log", session.scalar(select(func.count()).select_from(AuditLog)) or 0))
        if args.api_keys:
            planned.append(("api_keys", session.scalar(select(func.count()).select_from(ApiKey)) or 0))

        total = sum(n for _, n in planned)
        print(f"{'DELETING' if commit else 'DRY RUN — would delete'}:")
        for label, n in planned:
            print(f"  {label:28} {n}")
        print(f"  {'TOTAL':28} {total}")

        if not commit:
            print("\nNo changes made. Re-run with --yes to apply.")
            return 0

        for _, model in OPERATIONAL:
            session.execute(delete(model))
        if args.test_users:
            session.execute(delete(User).where(User.username.like(f"{TEST_USERNAME_PREFIX}%")))
        if args.audit:
            session.execute(delete(AuditLog))
        if args.api_keys:
            session.execute(delete(ApiKey))
        session.commit()
        print("\nDone.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
