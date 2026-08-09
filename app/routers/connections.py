"""Onboard an API by pasting its access key instead of uploading a spec.

`/registry/*` assumes you can produce an OpenAPI/Postman/curl artifact for the
API you want watched. For a third-party API — Claude, Gemini, OpenAI — you
can't: you have a key and nothing else. These routes close that gap by pairing
the pasted key with a built-in surface definition
(app/services/provider_catalog.py), seeding the same KnownEndpoint rows the
spec upload would have produced, and optionally proving the key is live.

The key itself is encrypted at rest (app/services/crypto.py) and never leaves
the server: every response carries only a masked prefix/last-4.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import OrgContext, get_current_user, require_org_role
from app.models import KnownEndpoint, MonitoredApi, User
from app.routers.auth import limiter
from app.schemas import ConnectedApiCreate, ConnectedApiOut, ProviderOut
from app.security import OrgRole, utc_now
from app.services.audit_service import log_audit_event
from app.services.crypto import DecryptionError, decrypt_secret, encrypt_secret, mask_secret
from app.services.discovery_service import recompute_discovered_documented_flags
from app.services.provider_catalog import (
    CUSTOM_PROVIDER_ID,
    Provider,
    get_provider,
    list_providers,
    validate_key_format,
)
from app.services.provider_probe import (
    STATUS_UNVERIFIED,
    UnsafeTargetError,
    assert_safe_target,
    probe,
)
from app.services.registry_service import register_paths

router = APIRouter(prefix="/connections", tags=["connections"])

_ENDPOINT_LINE_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)$", re.IGNORECASE)

# A custom connection's endpoint list is hand-typed, so it needs the bound the
# catalog providers get implicitly from being hard-coded.
MAX_CUSTOM_ENDPOINTS = 200


def _parse_endpoint_lines(text: str) -> list[tuple[str, str]]:
    """Parse "METHOD /path" lines into the (METHOD, template) tuples the
    registry speaks. Blank lines and `#` comments are skipped; anything else
    that doesn't parse is an error the operator should see rather than have
    silently dropped."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENDPOINT_LINE_RE.match(line)
        if not m:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot parse endpoint line {line!r} — expected e.g. 'GET /v1/health'.",
            )
        pair = (m.group(1).upper(), m.group(2))
        if pair in seen:
            continue
        seen.add(pair)
        out.append(pair)
    if len(out) > MAX_CUSTOM_ENDPOINTS:
        raise HTTPException(status_code=400, detail=f"Too many endpoints (max {MAX_CUSTOM_ENDPOINTS}).")
    return out


def _name_taken(db: Session, org_id: int, name: str) -> bool:
    return (
        db.query(MonitoredApi).filter(MonitoredApi.org_id == org_id, MonitoredApi.name == name).first()
        is not None
    )


def _to_out(row: MonitoredApi) -> ConnectedApiOut:
    provider = get_provider(row.provider)
    masked = f"{row.key_prefix}…{row.key_last4}" if row.key_last4 else f"{row.key_prefix}…"
    return ConnectedApiOut(
        id=row.id,
        name=row.name,
        provider=row.provider,
        provider_label=provider.label if provider else row.provider,
        base_url=row.base_url,
        key_masked=masked,
        endpoints_registered=row.endpoints_registered,
        status=row.status,
        last_checked_at=row.last_checked_at,
        last_check_detail=row.last_check_detail,
        created_at=row.created_at,
    )


def _resolve_target(body: ConnectedApiCreate, provider: Provider) -> tuple[str, str, list[tuple[str, str]]]:
    """Work out (base_url, verify_path, endpoints) for a create request.

    For catalog providers these come from the hard-coded definition — a client
    cannot repoint an "Anthropic" connection at another host, which keeps the
    stored credential tied to the service it was issued for.
    """
    if provider.id != CUSTOM_PROVIDER_ID:
        return provider.base_url, provider.verify_path, list(provider.endpoints)

    base_url = (body.base_url or "").strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is required for a custom API.")
    try:
        # Reject an unreachable-by-policy target at creation rather than
        # storing a row that can never be probed. A probe *failure* is a
        # status to display (the host might come back); a target we will
        # always refuse to send credentials to is a bad request.
        assert_safe_target(base_url)
    except UnsafeTargetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    endpoints = _parse_endpoint_lines(body.endpoints or "")
    if not endpoints:
        raise HTTPException(
            status_code=400,
            detail="List at least one endpoint to monitor, e.g. 'GET /v1/health'.",
        )
    return base_url, (body.verify_path or "/").strip() or "/", endpoints


@router.get("/providers")
def list_supported_providers(_ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER))) -> list[ProviderOut]:
    return [
        ProviderOut(
            id=p.id,
            label=p.label,
            base_url=p.base_url,
            key_hint=p.key_hint,
            docs_url=p.docs_url,
            endpoint_count=len(p.endpoints),
            requires_base_url=p.id == CUSTOM_PROVIDER_ID,
        )
        for p in list_providers()
    ]


@router.get("")
@limiter.limit("120/minute")
def list_connections(
    request: Request,
    ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER)),
    db: Session = Depends(get_db),
) -> list[ConnectedApiOut]:
    rows = (
        db.query(MonitoredApi)
        .filter(MonitoredApi.org_id == ctx.org_id)
        .order_by(MonitoredApi.id.desc())
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", status_code=201)
@limiter.limit("30/minute")
def create_connection(
    body: ConnectedApiCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> ConnectedApiOut:
    provider = get_provider(body.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider {body.provider!r}.")

    api_key = body.api_key.strip()
    if (reason := validate_key_format(provider, api_key)) is not None:
        raise HTTPException(status_code=400, detail=reason)

    name = body.name.strip()
    base_url, verify_path, endpoints = _resolve_target(body, provider)

    if _name_taken(db, ctx.org_id, name):
        raise HTTPException(status_code=409, detail=f"A connection named {name!r} already exists.")

    status, detail = STATUS_UNVERIFIED, None
    checked_at = None
    if body.verify:
        status, detail = probe(provider, api_key, base_url, verify_path)
        checked_at = utc_now()

    prefix, last4 = mask_secret(api_key)
    row = MonitoredApi(
        org_id=ctx.org_id,
        name=name,
        provider=provider.id,
        base_url=base_url,
        verify_path=verify_path,
        credential_ciphertext=encrypt_secret(api_key),
        key_prefix=prefix,
        key_last4=last4,
        status=status,
        last_checked_at=checked_at,
        last_check_detail=detail[:512] if detail else None,
        created_by=current_user.id,
    )
    db.add(row)
    try:
        db.flush()  # need row.id to tag the KnownEndpoints this connection owns
    except IntegrityError:
        # uq_monitored_api_org_name. The check above narrows the window but
        # can't close it — two concurrent creates both pass it, and the loser
        # should still read as a conflict rather than a 500.
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A connection named {name!r} already exists.") from None

    result = register_paths(
        db,
        ctx=ctx,
        current_user=current_user,
        request=request,
        title=name,
        paths=endpoints,
        source=f"connection:{row.id}",
        event_type="api_connection_created",
        extra_details={"provider": provider.id, "verified": status},
    )
    # The provider's whole surface, not just the rows this call newly inserted
    # — "Claude covers 12 endpoints" is what the operator wants to read, and a
    # second connection to the same provider would otherwise report 0.
    row.endpoints_registered = result["paths_found"]
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post("/{connection_id}/verify")
@limiter.limit("30/minute")
def verify_connection(
    connection_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> ConnectedApiOut:
    row = (
        db.query(MonitoredApi)
        .filter(MonitoredApi.id == connection_id, MonitoredApi.org_id == ctx.org_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    provider = get_provider(row.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider {row.provider!r}.")

    try:
        api_key = decrypt_secret(row.credential_ciphertext)
    except DecryptionError as e:
        # 409, not 500: the row is intact, the encryption key moved out from
        # under it, and the fix is an operator action (re-enter the key).
        raise HTTPException(status_code=409, detail=str(e)) from e

    status, detail = probe(provider, api_key, row.base_url, row.verify_path)
    row.status = status
    row.last_check_detail = detail[:512]
    row.last_checked_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="api_connection_verified",
        actor=current_user.username,
        target=row.name,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"provider": row.provider, "status": status},
        success=status != "error",
    )
    db.refresh(row)
    return _to_out(row)


@router.delete("/{connection_id}", status_code=200)
@limiter.limit("30/minute")
def delete_connection(
    connection_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(require_org_role(OrgRole.EDITOR)),
    db: Session = Depends(get_db),
) -> dict:
    row = (
        db.query(MonitoredApi)
        .filter(MonitoredApi.id == connection_id, MonitoredApi.org_id == ctx.org_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Connection not found.")

    # Drop the endpoints this connection seeded, otherwise the idle/zombie
    # scanners keep alerting on a surface nobody monitors any more. Endpoints
    # that also arrived from a spec upload have a different `source` and are
    # left alone.
    removed = (
        db.query(KnownEndpoint)
        .filter(KnownEndpoint.org_id == ctx.org_id, KnownEndpoint.source == f"connection:{row.id}")
        .delete(synchronize_session=False)
    )
    name = row.name
    provider_id = row.provider
    db.delete(row)
    db.commit()
    recompute_discovered_documented_flags(db, ctx.org_id)
    log_audit_event(
        db,
        event_type="api_connection_deleted",
        actor=current_user.username,
        target=name,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        details={"provider": provider_id, "endpoints_removed": removed},
        success=True,
    )
    return {"deleted": True, "endpoints_removed": removed}
