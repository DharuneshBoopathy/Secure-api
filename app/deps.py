"""Authentication & authorization dependencies for FastAPI routes.

Provides:
- ``get_current_user``  – resolves the caller to a ``User`` row (JWT or API key)
- ``require_role(min_role)`` – factory that returns a dependency enforcing a minimum role
- ``verify_monitor_key``   – legacy compatibility wrapper (unchanged interface)
"""

from __future__ import annotations

import secrets as _secrets

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.security import Role, decode_token


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
    if x_monitor_key and _secrets.compare_digest(x_monitor_key, settings.monitor_api_key):
        return _get_system_admin(db, settings.admin_username)

    # --- Try query parameter fallback ---
    # Credentials in query strings end up in nginx access logs, proxy logs,
    # browser history, and Referer headers, so this path is opt-in only.
    if auth and settings.allow_query_auth:
        if _secrets.compare_digest(auth, settings.monitor_api_key):
            return _get_system_admin(db, settings.admin_username)
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
        except Exception:
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
            except Exception:
                pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
    )
