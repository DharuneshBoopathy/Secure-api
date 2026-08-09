"""Turning extracted (method, path template) pairs into monitored endpoints.

Every onboarding route converges here — OpenAPI, Postman and curl uploads via
app/routers/openapi_registry.py, and key-based connections via
app/routers/connections.py. Each has its own extraction step, but once a
source is reduced to plain (METHOD, template) tuples the work is identical:
dedupe into KnownEndpoint, re-flag discovered traffic, audit-log the import.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from app.deps import OrgContext
from app.models import KnownEndpoint, User
from app.services.audit_service import log_audit_event
from app.services.discovery_service import recompute_discovered_documented_flags


def register_paths(
    db: Session,
    *,
    ctx: OrgContext,
    current_user: User,
    request: Request,
    title: str,
    paths: list[tuple[str, str]],
    source: str,
    event_type: str,
    extra_details: dict | None = None,
) -> dict:
    added = 0
    for method, path_template in paths:
        exists = (
            db.query(KnownEndpoint)
            .filter(
                KnownEndpoint.org_id == ctx.org_id,
                KnownEndpoint.method == method.upper(),
                KnownEndpoint.path_template == path_template,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            KnownEndpoint(
                org_id=ctx.org_id,
                method=method.upper(),
                path_template=path_template,
                source=source,
            )
        )
        added += 1
    db.commit()
    recompute_discovered_documented_flags(db, ctx.org_id)
    log_audit_event(
        db,
        event_type=event_type,
        actor=current_user.username,
        target=title,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"paths_registered": added, "paths_found": len(paths), **(extra_details or {})},
        success=True,
    )
    return {"paths_registered": added, "paths_found": len(paths)}
