"""Authentication & authorization dependencies for FastAPI routes.

Provides:
- ``get_current_user``  – resolves the caller to a ``User`` row (JWT or API key)
- ``require_role(min_role)`` – factory that returns a dependency enforcing a minimum role
- ``verify_monitor_key``   – legacy compatibility wrapper (unchanged interface)
"""

from __future__ import annotations

import secrets as _secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ApiKey, Organization, OrgMembership, User
from app.security import API_KEY_PREFIX, OrgRole, Role, decode_token, hash_token, utc_now
from app.services.audit_service import log_audit_event


# ---------------------------------------------------------------------------
# Core: resolve current user from JWT bearer token
# ---------------------------------------------------------------------------

def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_monitor_key: str | None = Header(default=None, alias="X-Monitor-Key"),
    auth: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Extract and validate the caller identity. Returns the User ORM object.

    Accepts (in priority order):
    1. Authorization: Bearer <access-jwt>
    2. X-Monitor-Key header (maps to the system admin user)
    3. ?auth= query parameter (JWT or monitor key)
    """
    settings = get_settings()

    # --- Try Bearer JWT first ---
    user = _try_jwt(authorization, db)
    if user:
        return user

    # --- Try API key header (constant-time compare prevents timing leaks) ---
    if x_monitor_key:
        if _secrets.compare_digest(x_monitor_key, settings.monitor_api_key):
            return _get_system_admin(db, settings.admin_username)
        api_key_user = _try_api_key(x_monitor_key, db)
        if api_key_user:
            return api_key_user

    # --- Try query parameter fallback ---
    # Credentials in query strings end up in nginx access logs, proxy logs,
    # browser history, and Referer headers, so this path is opt-in only.
    if auth and settings.allow_query_auth:
        if _secrets.compare_digest(auth, settings.monitor_api_key):
            return _get_system_admin(db, settings.admin_username)
        api_key_user = _try_api_key(auth, db)
        if api_key_user:
            return api_key_user
        if auth.startswith("Bearer "):
            user = _try_jwt(auth, db)
            if user:
                return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _try_jwt(header_value: str | None, db: Session) -> User | None:
    """Attempt to extract a valid access JWT and return the User, or None."""
    if not header_value:
        return None
    token = header_value
    if header_value.startswith("Bearer "):
        token = header_value.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token)
        if payload.get("type") != "access" or not payload.get("sub"):
            return None
        user = (
            db.query(User)
            .filter(User.username == payload["sub"], User.is_active.is_(True))
            .one_or_none()
        )
        return user
    except Exception:
        return None


def _try_api_key(raw_key: str, db: Session) -> User | None:
    """Resolve a per-integration API key (see ApiKey) to a synthetic, never-
    persisted User carrying the key's assigned role. Not saved via db.add()
    — this only ever flows through RBAC checks and audit-log actor strings,
    neither of which requires (or should get) a real users-table row.
    """
    if not raw_key.startswith(API_KEY_PREFIX):
        return None
    row = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == hash_token(raw_key), ApiKey.revoked.is_(False))
        .one_or_none()
    )
    if row is None:
        return None
    row.last_used_at = utc_now()
    db.commit()
    user = User(
        id=0,
        username=f"apikey:{row.name}",
        email=None,
        password_hash="",  # nosec B106 — not a credential: this transient User (id=0, never persisted) represents an API key, not a password login; there is no password to hash
        role=row.role,
        is_active=True,
        created_at=row.created_at,
    )
    # Not a mapped column — carries the key's fixed org binding through to
    # get_org_context() without a real OrgMembership row (the transient user
    # above is never persisted, so it can't have one). A key belongs to
    # exactly one org for its whole lifetime; see docs/adr/002.
    user._api_key_org_id = row.org_id  # type: ignore[attr-defined]
    return user


def _get_system_admin(db: Session, admin_username: str) -> User:
    """Return the default admin user for API-key authenticated requests."""
    user = (
        db.query(User)
        .filter(User.username == admin_username, User.is_active.is_(True))
        .one_or_none()
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="System admin user not found",
        )
    return user


# ---------------------------------------------------------------------------
# Role-based access control dependency factory
# ---------------------------------------------------------------------------

def require_role(min_role: Role):
    """Return a FastAPI dependency that enforces a minimum role level.

    Usage::

        @router.get("/admin-only", dependencies=[Depends(require_role(Role.ADMIN))])
        def admin_only(): ...

    Or inject the user directly::

        @router.get("/data")
        def get_data(user: User = Depends(require_role(Role.EDITOR))):
            ...
    """
    def _check(current_user: User = Depends(get_current_user)) -> User:
        try:
            user_role = Role(current_user.role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Unknown role '{current_user.role}'",
            )
        if user_role < min_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires '{min_role.value}' role or higher",
            )
        return current_user
    return _check


# ---------------------------------------------------------------------------
# Convenience aliases
# ---------------------------------------------------------------------------

require_admin = require_role(Role.ADMIN)
require_editor = require_role(Role.EDITOR)
require_viewer = require_role(Role.VIEWER)


# ---------------------------------------------------------------------------
# Org-scoped RBAC (see docs/adr/002-multi-tenancy-schema.md)
#
# Distinct from require_role() above: that gates platform-level actions
# (user/API-key/MFA management, the full audit log). This gates org-scoped
# *resources* (traffic, alerts, shadow/zombie endpoints, anomalies,
# inventory, the OpenAPI registry, ingest) by the caller's role within one
# specific organization.
# ---------------------------------------------------------------------------

@dataclass
class OrgContext:
    org_id: int
    role: OrgRole
    is_cross_org_admin: bool = False


def get_org_context(
    request: Request,
    x_org_id: int | None = Header(default=None, alias="X-Org-Id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrgContext:
    """Resolve which organization this request acts on (header-authenticated
    callers). See ``_resolve_org_context`` for the rules."""
    return _resolve_org_context(request, x_org_id, current_user, db)


def _resolve_org_context(
    request: Request,
    x_org_id: int | None,
    current_user: User,
    db: Session,
) -> OrgContext:
    """Resolve which organization this request acts on, and the caller's
    role within it.

    - Per-integration API keys carry a fixed org binding (see _try_api_key)
      and never cross-org — X-Org-Id is ignored for them.
    - X-Org-Id explicit: requires an active membership in that org, UNLESS
      the caller is a platform admin, in which case cross-org access is
      allowed but audit-logged (never silent).
    - X-Org-Id omitted: falls back to the caller's sole active membership,
      so single-tenant deployments (and every pre-multi-tenancy automation
      client) keep working with zero configuration. Ambiguous (0 or 2+
      memberships) without an explicit header is a 400, not a guess.
    """
    api_key_org_id = getattr(current_user, "_api_key_org_id", None)
    if api_key_org_id is not None:
        return OrgContext(org_id=api_key_org_id, role=OrgRole(current_user.role))

    if x_org_id is not None:
        membership = (
            db.query(OrgMembership)
            .filter(
                OrgMembership.user_id == current_user.id,
                OrgMembership.org_id == x_org_id,
                OrgMembership.status == "active",
            )
            .one_or_none()
        )
        if membership is not None:
            return OrgContext(org_id=x_org_id, role=OrgRole(membership.role))

        if current_user.role == Role.ADMIN.value:
            org = db.query(Organization).filter(Organization.id == x_org_id).one_or_none()
            if org is not None:
                log_audit_event(
                    db,
                    event_type="cross_org_access",
                    actor=current_user.username,
                    target=f"org/{x_org_id}",
                    ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    success=True,
                )
                return OrgContext(org_id=x_org_id, role=OrgRole.OWNER, is_cross_org_admin=True)

        raise HTTPException(status_code=403, detail="No active membership in the requested organization")

    memberships = (
        db.query(OrgMembership)
        .filter(OrgMembership.user_id == current_user.id, OrgMembership.status == "active")
        .all()
    )
    if len(memberships) == 1:
        m = memberships[0]
        return OrgContext(org_id=m.org_id, role=OrgRole(m.role))
    if not memberships:
        raise HTTPException(
            status_code=400,
            detail="No organization membership — join an organization or pass X-Org-Id",
        )
    raise HTTPException(
        status_code=400,
        detail="Caller belongs to multiple organizations — specify X-Org-Id",
    )


def require_org_role(min_role: OrgRole):
    """Return a FastAPI dependency that enforces a minimum org-scoped role.

    Usage::

        @router.get("/alerts")
        def list_alerts(ctx: OrgContext = Depends(require_org_role(OrgRole.VIEWER))):
            ...
    """
    def _check(ctx: OrgContext = Depends(get_org_context)) -> OrgContext:
        if ctx.role < min_role:
            raise HTTPException(
                status_code=403,
                detail=f"Requires org role '{min_role.value}' or higher",
            )
        return ctx
    return _check


# ---------------------------------------------------------------------------
# Server-sent events
# ---------------------------------------------------------------------------

def get_stream_org_context(
    request: Request,
    ticket: str | None = Query(default=None),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_monitor_key: str | None = Header(default=None, alias="X-Monitor-Key"),
    x_org_id: int | None = Header(default=None, alias="X-Org-Id"),
    db: Session = Depends(get_db),
) -> OrgContext:
    """Resolve the org context for an SSE endpoint.

    Browsers cannot attach headers to an EventSource, so a credential opening
    a stream has to travel in the URL — where it lands in access logs. Only a
    stream ticket is accepted there (see ``create_stream_ticket``): it expires
    in a minute and every other route rejects its ``type``, so a ticket
    scraped from a log buys far less than an access token would.

    The ticket also carries the organization it was minted for, because the
    X-Org-Id header is just as unavailable to EventSource as Authorization is.

    Non-browser clients (curl, integration scripts) authenticate by header as
    normal, which keeps nothing in the URL at all.
    """
    if authorization or x_monitor_key:
        user = get_current_user(
            x_monitor_key=x_monitor_key, authorization=authorization, auth=None, db=db
        )
        return _resolve_org_context(request, x_org_id, user, db)

    if ticket:
        try:
            payload = decode_token(ticket)
        except Exception:  # nosec B110 — an unparseable ticket is just a 401
            payload = None
        if payload and payload.get("type") == "stream" and payload.get("sub"):
            ticket_user = (
                db.query(User)
                .filter(User.username == payload["sub"], User.is_active.is_(True))
                .first()
            )
            org_id = payload.get("org")
            if ticket_user is not None and isinstance(org_id, int):
                # Re-check membership at connect time rather than trusting the
                # claim: a ticket minted before the user was removed from the
                # org must not still open a stream into it.
                membership = (
                    db.query(OrgMembership)
                    .filter(
                        OrgMembership.user_id == ticket_user.id,
                        OrgMembership.org_id == org_id,
                        OrgMembership.status == "active",
                    )
                    .one_or_none()
                )
                if membership is not None:
                    return OrgContext(org_id=org_id, role=OrgRole(membership.role))
                if ticket_user.role == Role.ADMIN.value:
                    return OrgContext(org_id=org_id, role=OrgRole.OWNER, is_cross_org_admin=True)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired stream ticket",
    )


def require_stream_org_role(min_role: OrgRole):
    """``require_org_role`` for the SSE endpoints — same check, ticket-aware
    resolution."""

    def _check(ctx: OrgContext = Depends(get_stream_org_context)) -> OrgContext:
        if ctx.role < min_role:
            raise HTTPException(
                status_code=403,
                detail=f"Requires org role '{min_role.value}' or higher",
            )
        return ctx

    return _check


# ---------------------------------------------------------------------------
# Legacy compatibility – keeps existing route signatures working
# ---------------------------------------------------------------------------

def verify_monitor_key(
    x_monitor_key: str | None = Header(default=None, alias="X-Monitor-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    auth: str | None = Query(default=None),
) -> None:
    """Backward-compatible auth check (does NOT resolve a User object).

    Kept so that existing ``dependencies=[Depends(verify_monitor_key)]`` still
    compile.  New routes should use ``require_role()`` or ``get_current_user``.
    """
    settings = get_settings()
    if x_monitor_key and _secrets.compare_digest(x_monitor_key, settings.monitor_api_key):
        return
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        try:
            payload = decode_token(token)
            if payload.get("type") == "access" and payload.get("sub"):
                return
        except Exception:  # nosec B110
            pass
    if auth and settings.allow_query_auth:
        if _secrets.compare_digest(auth, settings.monitor_api_key):
            return
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()
            try:
                payload = decode_token(token)
                if payload.get("type") == "access" and payload.get("sub"):
                    return
            except Exception:  # nosec B110
                pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
    )
