"""Authentication, registration, and user-management routes."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_role
from app.models import RefreshToken, User
from app.schemas import (
    AdminCreateUserIn,
    AuthOut,
    ChangePasswordIn,
    LoginIn,
    RegisterIn,
    TokenRefreshIn,
    UserOut,
    UserUpdateIn,
)
from app.security import (
    DUMMY_PASSWORD_HASH,
    PasswordValidationError,
    Role,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    utc_now,
    validate_password_strength,
    verify_password,
)
from app.services.audit_service import log_audit_event

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_user_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def _build_auth_out(user: User, access_token: str, access_exp: datetime, refresh_token: str) -> AuthOut:
    expires_in = int((access_exp - utc_now()).total_seconds())
    return AuthOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=max(0, expires_in),
        user=_build_user_out(user),
    )


# ---------------------------------------------------------------------------
# Public: login / register / refresh / logout
# ---------------------------------------------------------------------------

@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    user = db.query(User).filter(User.username == body.username, User.is_active.is_(True)).one_or_none()
    # Always run a bcrypt comparison so response time does not leak whether
    # the username exists.  When the user is missing we hash against a
    # module-level dummy; the result is discarded.
    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        ok = False
    else:
        ok = verify_password(body.password, user.password_hash)
    if not ok:
        log_audit_event(
            db,
            event_type="login_attempt",
            actor=body.username,
            target="auth/login",
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=False,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    assert user is not None  # nosec B101 - type narrowing only; user is non-None when ok=True
    access_token, access_exp = create_access_token(user.username)
    refresh_token, refresh_exp = create_refresh_token(user.username)
    db.add(RefreshToken(user_id=user.id, token=hash_token(refresh_token), expires_at=refresh_exp, revoked=False))
    db.commit()
    log_audit_event(
        db,
        event_type="login_attempt",
        actor=user.username,
        target="auth/login",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return _build_auth_out(user, access_token, access_exp, refresh_token)


@router.post("/register", status_code=201)
@limiter.limit("3/minute")
def register(request: Request, body: RegisterIn, db: Session = Depends(get_db)) -> AuthOut:
    """Self-registration: creates a new user with 'viewer' role."""
    # Password strength
    try:
        validate_password_strength(body.password)
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Uniqueness checks
    if db.query(User).filter(User.username == body.username).one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == body.email).one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=Role.VIEWER.value,
        is_active=True,
    )
    db.add(user)
    db.flush()  # get user.id

    access_token, access_exp = create_access_token(user.username)
    refresh_token, refresh_exp = create_refresh_token(user.username)
    db.add(RefreshToken(user_id=user.id, token=hash_token(refresh_token), expires_at=refresh_exp, revoked=False))
    db.commit()

    log_audit_event(
        db,
        event_type="user_registered",
        actor=user.username,
        target="auth/register",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return _build_auth_out(user, access_token, access_exp, refresh_token)


@router.post("/refresh")
@limiter.limit("10/minute")
def refresh(request: Request, body: TokenRefreshIn, db: Session = Depends(get_db)) -> AuthOut:
    token_hash = hash_token(body.refresh_token)
    # Atomic compare-and-revoke: only one concurrent /refresh for the same
    # token can flip revoked=False → True. Without this, two requests racing
    # on the same token could both pass the check and mint independent chains.
    updated = (
        db.query(RefreshToken)
        .filter(RefreshToken.token == token_hash, RefreshToken.revoked.is_(False))
        .update({"revoked": True}, synchronize_session=False)
    )
    if updated == 0:
        # Either the token never existed, or it existed and was already
        # revoked. The second case is a replay of a rotated token — treat
        # it as a compromise indicator and revoke the user's whole chain.
        replayed = db.query(RefreshToken).filter(RefreshToken.token == token_hash).one_or_none()
        if replayed is not None:
            db.query(RefreshToken).filter(
                RefreshToken.user_id == replayed.user_id,
                RefreshToken.revoked.is_(False),
            ).update({"revoked": True}, synchronize_session=False)
            db.commit()
            log_audit_event(
                db,
                event_type="refresh_token_reuse",
                actor=str(replayed.user_id),
                target="auth/refresh",
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False,
            )
        else:
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    db.commit()
    row = db.query(RefreshToken).filter(RefreshToken.token == token_hash).one()
    if row.expires_at <= utc_now():
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        payload = decode_token(body.refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    username = str(payload.get("sub") or "")
    user = db.query(User).filter(User.username == username, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    access_token, access_exp = create_access_token(user.username)
    new_refresh, refresh_exp = create_refresh_token(user.username)
    db.add(RefreshToken(user_id=user.id, token=hash_token(new_refresh), expires_at=refresh_exp, revoked=False))
    db.commit()
    log_audit_event(
        db,
        event_type="token_refresh",
        actor=user.username,
        target="auth/refresh",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return _build_auth_out(user, access_token, access_exp, new_refresh)


@router.post("/logout")
@limiter.limit("20/minute")
def logout(request: Request, body: TokenRefreshIn, db: Session = Depends(get_db)) -> dict:
    row = db.query(RefreshToken).filter(RefreshToken.token == hash_token(body.refresh_token)).one_or_none()
    if row:
        row.revoked = True
        db.commit()
    return {"logged_out": True}


# ---------------------------------------------------------------------------
# Authenticated: profile / change password
# ---------------------------------------------------------------------------

@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the authenticated user's profile."""
    return _build_user_out(current_user)


@router.put("/me/password")
@limiter.limit("5/minute")
def change_password(
    request: Request,
    body: ChangePasswordIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Change own password (any role)."""
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        validate_password_strength(body.new_password)
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    current_user.password_hash = hash_password(body.new_password)
    db.commit()
    log_audit_event(
        db,
        event_type="password_changed",
        actor=current_user.username,
        target=f"user/{current_user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"message": "Password updated successfully"}


# ---------------------------------------------------------------------------
# Admin: user management (CRUD)
# ---------------------------------------------------------------------------

@router.get("/users", dependencies=[Depends(require_role(Role.ADMIN))])
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    """List all users (admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [_build_user_out(u) for u in users]


@router.post("/users", status_code=201)
@limiter.limit("10/minute")
def admin_create_user(
    request: Request,
    body: AdminCreateUserIn,
    current_user: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> UserOut:
    """Create a new user with a specified role (admin only)."""
    try:
        validate_password_strength(body.password)
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if db.query(User).filter(User.username == body.username).one_or_none():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == body.email).one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=body.is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_audit_event(
        db,
        event_type="user_created_by_admin",
        actor=current_user.username,
        target=f"user/{user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"new_username": user.username, "role": user.role},
    )
    return _build_user_out(user)


@router.get("/users/{user_id}", dependencies=[Depends(require_role(Role.ADMIN))])
def get_user(user_id: int, db: Session = Depends(get_db)) -> UserOut:
    """Get a single user by ID (admin only)."""
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _build_user_out(user)


@router.patch("/users/{user_id}")
@limiter.limit("10/minute")
def update_user(
    request: Request,
    user_id: int,
    body: UserUpdateIn,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> UserOut:
    """Update a user's role, email, or active status (admin only)."""
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.email is not None:
        existing = db.query(User).filter(User.email == body.email, User.id != user_id).one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")
        user.email = body.email
    if body.role is not None:
        if not Role.has_value(body.role):
            raise HTTPException(status_code=422, detail=f"Invalid role: {body.role}")
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    log_audit_event(
        db,
        event_type="user_updated_by_admin",
        actor=admin.username,
        target=f"user/{user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"changes": body.model_dump(exclude_none=True)},
    )
    return _build_user_out(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    request: Request,
    user_id: int,
    admin: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    """Deactivate a user (soft delete – admin only). Cannot deactivate self."""
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    user.is_active = False
    # Revoke all active refresh tokens
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})
    db.commit()
    log_audit_event(
        db,
        event_type="user_deactivated_by_admin",
        actor=admin.username,
        target=f"user/{user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )


# ---------------------------------------------------------------------------
# Bootstrap: ensure default admin exists on startup
# ---------------------------------------------------------------------------

def ensure_default_admin(db: Session) -> None:
    settings = get_settings()
    user = db.query(User).filter(User.username == settings.admin_username).one_or_none()
    is_dev = settings.app_env != "production"

    if user is None:
        # First-ever boot: create the admin account with the config-supplied password
        # (auto-generated by default_factory if not set in the environment).
        password = settings.admin_password
        db.add(
            User(
                username=settings.admin_username,
                password_hash=hash_password(password),
                role="admin",
                is_active=True,
            )
        )
        db.commit()
        # Never write plaintext credentials to the log in production — log
        # aggregators (SIEM / Loki / CloudWatch) index and retain them.
        if is_dev:
            log.warning("DEV-ONLY initial admin password: %s", password)
        else:
            log.info(
                "Admin account '%s' created from ADMIN_PASSWORD env var.",
                settings.admin_username,
            )
        return

    # Account already exists — rotate if it still holds the known legacy literal "admin".
    if verify_password("admin", user.password_hash):
        password = settings.admin_password
        user.password_hash = hash_password(password)
        db.commit()
        if is_dev:
            log.warning(
                "Admin account had a weak default password and has been rotated. "
                "New password: %s",
                password,
            )
        else:
            log.warning(
                "Admin account '%s' had the legacy 'admin' password and has "
                "been rotated to the ADMIN_PASSWORD value from the environment.",
                settings.admin_username,
            )
