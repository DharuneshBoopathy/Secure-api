import json
import logging
import sys

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.security import utc_now

# ---------------------------------------------------------------------------
# Dedicated structured-JSON logger for audit events.
#
# Using a %(message)s-only formatter and propagate=False means each audit
# record lands on stdout as a single, parseable JSON line with no extra
# log-framework metadata (level, logger name, etc.) wrapping it.  This is
# the format expected by SIEM / log-aggregation pipelines that consume
# Docker stdout streams.
# ---------------------------------------------------------------------------
_audit_log = logging.getLogger("audit")

if not _audit_log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_log.addHandler(_handler)
    _audit_log.setLevel(logging.INFO)
    _audit_log.propagate = False  # prevent double-emission via root logger


def log_audit_event(
    db: Session,
    *,
    event_type: str,
    actor: str,
    target: str | None,
    ip: str | None,
    user_agent: str | None,
    details: dict | None = None,
    success: bool = True,
) -> None:
    # Capture timestamp once so both the DB row and the JSON log carry
    # the exact same value.
    now = utc_now()

    row = AuditLog(
        event_type=event_type,
        actor=actor,
        target=target,
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
        timestamp=now,
        details=details or {},
        success=success,
    )
    db.add(row)
    db.commit()

    # Emit a structured JSON audit record to stdout synchronously with the
    # DB commit.  The stdout record only fires after a successful commit so
    # the two sinks remain consistent.
    _audit_log.info(
        json.dumps(
            {
                "audit": True,
                "event_type": event_type,
                "actor": actor,
                "target": target,
                "ip": ip,
                "user_agent": user_agent,
                "timestamp": now.isoformat(),
                "success": success,
                "details": details or {},
            },
            default=str,  # serialize any non-JSON-native types (e.g. datetime)
        )
    )
