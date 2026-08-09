"""Authentication, registration, and user-management routes."""

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import OrgContext, get_current_user, get_org_context, require_role
from app.models import ApiKey, Organization, OrgMembership, PasswordResetToken, RefreshToken, User
from app.schemas import (
    AdminCreateUserIn,
    ApiKeyCreatedOut,
    ApiKeyCreateIn,
    ApiKeyOut,
    AuthOut,
    ChangePasswordIn,
    LoginIn,
    MfaCodeIn,
    MfaEnrollOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    RegisterIn,
    TokenRefreshIn,
    UserOut,
    UserUpdateIn,
)
from app.security import (
    DUMMY_PASSWORD_HASH,
    PasswordValidationError,
    Role,
    api_key_display_prefix,
    build_totp_uri,
    create_access_token,
    create_refresh_token,
    create_stream_ticket,
    decode_token,
    generate_api_key,
    generate_totp_secret,
    hash_password,
    hash_token,
    utc_now,
    validate_password_strength,
    verify_password,
    verify_totp,
)
from app.services import mailer
from app.services.audit_service import log_audit_event

log = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
# In-memory (default) means rate limits are per-process — correct for one
# replica, but each replica behind nginx enforces its own separate counters
# once you run more than one, silently multiplying the effective limit.
# Setting REDIS_URL makes limits correct cluster-wide (see the "worker"
# service in docker-compose.yml, which sets it alongside "web").
limiter = Limiter(key_func=get_remote_address, storage_uri=get_settings().redis_url or "memory://")


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

def _lockout_seconds(settings, failed_count: int) -> int:
    """Exponential backoff duration for the (failed_count - threshold)th lockout."""
    over = failed_count - settings.login_lockout_threshold
    return min(
        settings.login_lockout_base_seconds * (2**over),
        settings.login_lockout_max_seconds,
    )


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, body: LoginIn, db: Session = Depends(get_db)) -> AuthOut:
    settings = get_settings()
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user = db.query(User).filter(User.username == body.username, User.is_active.is_(True)).one_or_none()

    if user is not None and user.locked_until is not None and user.locked_until > utc_now():
        log_audit_event(
            db,
            event_type="login_attempt",
            actor=body.username,
            target="auth/login",
            ip=ip,
            user_agent=user_agent,
            success=False,
            details={"reason": "account_locked"},
        )
        raise HTTPException(status_code=423, detail="Account temporarily locked due to repeated failed logins")

    # Always run a bcrypt comparison so response time does not leak whether
    # the username exists.  When the user is missing we hash against a
    # module-level dummy; the result is discarded.
    if user is None:
        verify_password(body.password, DUMMY_PASSWORD_HASH)
        ok = False
    else:
        ok = verify_password(body.password, user.password_hash)

    # MFA is only checked once the password itself is correct — this
    # intentionally reveals "MFA required" solely to a caller who already
    # holds valid credentials, matching standard second-factor UX.
    failure_detail = "Invalid credentials"
    failure_reason = None
    if ok and user is not None and user.role == Role.ADMIN.value and user.mfa_enabled:
        if not body.mfa_code:
            ok = False
            failure_detail = "MFA code required"
            failure_reason = "mfa_code_required"
        elif not verify_totp(user.mfa_secret or "", body.mfa_code):
            ok = False
            failure_detail = "Invalid MFA code"
            failure_reason = "mfa_code_invalid"

    if not ok:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_lockout_threshold:
                seconds = _lockout_seconds(settings, user.failed_login_count)
                user.locked_until = utc_now() + timedelta(seconds=seconds)
                db.commit()
                log_audit_event(
                    db,
                    event_type="account_locked",
                    actor=user.username,
                    target="auth/login",
                    ip=ip,
                    user_agent=user_agent,
                    success=False,
                    details={"failed_login_count": user.failed_login_count, "locked_for_seconds": seconds},
                )
            else:
                db.commit()
        log_audit_event(
            db,
            event_type="login_attempt",
            actor=body.username,
            target="auth/login",
            ip=ip,
            user_agent=user_agent,
            success=False,
            details={"reason": failure_reason} if failure_reason else None,
        )
        raise HTTPException(status_code=401, detail=failure_detail)

    assert user is not None  # nosec B101 - type narrowing only; user is non-None when ok=True
    user.failed_login_count = 0
    user.locked_until = None
    access_token, access_exp = create_access_token(user.username)
    refresh_token, refresh_exp = create_refresh_token(user.username)
    db.add(RefreshToken(user_id=user.id, token=hash_token(refresh_token), expires_at=refresh_exp, revoked=False))
    db.commit()
    log_audit_event(
        db,
        event_type="login_attempt",
        actor=user.username,
        target="auth/login",
        ip=ip,
        user_agent=user_agent,
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


@router.post("/stream-ticket")
@limiter.limit("60/minute")
def issue_stream_ticket(
    request: Request,
    current_user: User = Depends(get_current_user),
    ctx: OrgContext = Depends(get_org_context),
) -> dict:
    """Exchange a normal header credential for a short-lived SSE ticket.

    This request carries its credential in headers as usual; only the ticket
    it returns ever appears in a URL. The limit is generous because the
    browser re-mints on every stream reconnect, and EventSource reconnects on
    any transient network blip.
    """
    ticket, expires_in = create_stream_ticket(current_user.username, ctx.org_id)
    return {"ticket": ticket, "expires_in": expires_in}


@router.post("/logout")
@limiter.limit("20/minute")
def logout(request: Request, body: TokenRefreshIn, db: Session = Depends(get_db)) -> dict:
    row = db.query(RefreshToken).filter(RefreshToken.token == hash_token(body.refresh_token)).one_or_none()
    if row:
        row.revoked = True
        db.commit()
    return {"logged_out": True}


# ---------------------------------------------------------------------------
# Public: password reset (forgot password)
# ---------------------------------------------------------------------------

_RESET_REQUEST_GENERIC_RESPONSE = {
    "message": "If an account with that email exists, a password reset link has been sent."
}


@router.post("/password-reset/request")
@limiter.limit("5/minute")
def request_password_reset(request: Request, body: PasswordResetRequestIn, db: Session = Depends(get_db)) -> dict:
    """Issue a short-lived, single-use password reset token.

    Always returns the same generic response whether or not the email is
    registered, so this endpoint cannot be used to enumerate accounts.
    """
    settings = get_settings()
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    user = db.query(User).filter(User.email == body.email, User.is_active.is_(True)).one_or_none()
    if user is None:
        return _RESET_REQUEST_GENERIC_RESPONSE

    raw_token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(minutes=settings.password_reset_token_expire_minutes)
    db.add(PasswordResetToken(user_id=user.id, token=hash_token(raw_token), expires_at=expires, used=False))
    db.commit()
    log_audit_event(
        db,
        event_type="password_reset_requested",
        actor=user.username,
        target=f"user/{user.id}",
        ip=ip,
        user_agent=user_agent,
        success=True,
    )
    # The token must reach the account owner and nobody else. It is never
    # logged in production and never returned in the response: application
    # logs are routinely shipped to a log aggregator, and a reset token in
    # that stream is an account-takeover primitive for everyone with log read
    # access.
    if mailer.is_configured() and user.email:
        try:
            mailer.send_password_reset(to=user.email, username=user.username, token=raw_token)
        except Exception:
            # Don't leak delivery failure to the caller — the response is
            # deliberately identical for known and unknown addresses, and
            # varying it here would reintroduce account enumeration.
            log.exception("Password reset email to user '%s' failed to send", user.username)
    elif settings.app_env == "production":
        log.error(
            "Password reset requested for '%s' but no SMTP transport is configured; the token "
            "was discarded. Set SMTP_HOST to enable self-service reset, or reset this account "
            "manually as an administrator.",
            user.username,
        )
    else:
        # Local development without a mail server: log it so the flow can be
        # completed by hand. Guarded on non-production precisely because this
        # line is the leak the rest of this block exists to avoid.
        log.warning(
            "Password reset requested for '%s'. DEV ONLY — deliver out-of-band: %s",
            user.username,
            raw_token,
        )
    return _RESET_REQUEST_GENERIC_RESPONSE


@router.post("/password-reset/confirm")
@limiter.limit("5/minute")
def confirm_password_reset(request: Request, body: PasswordResetConfirmIn, db: Session = Depends(get_db)) -> dict:
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    token_hash = hash_token(body.token)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token == token_hash, PasswordResetToken.used.is_(False))
        .one_or_none()
    )
    if row is None or row.expires_at <= utc_now():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == row.user_id, User.is_active.is_(True)).one_or_none()
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    try:
        validate_password_strength(body.new_password)
    except PasswordValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    user.password_hash = hash_password(body.new_password)
    user.failed_login_count = 0
    user.locked_until = None
    row.used = True
    # Invalidate any other outstanding reset tokens for this user so an
    # older, still-valid token can't be used after the password has changed.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
    ).update({"used": True})
    # A password reset should kill every existing session, not just future logins.
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})
    db.commit()
    log_audit_event(
        db,
        event_type="password_reset_completed",
        actor=user.username,
        target=f"user/{user.id}",
        ip=ip,
        user_agent=user_agent,
        success=True,
    )
    return {"message": "Password has been reset successfully"}


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
# Admin: TOTP MFA enrollment
#
# Restricted to the admin role — the role that holds full audit-log and
# user-management power is the one that needs a second factor. Enrollment
# requires proof of possession (one valid code) before mfa_enabled flips on,
# and disabling requires a valid code too, so a hijacked session token alone
# can't silently strip MFA off the account.
# ---------------------------------------------------------------------------

@router.post("/mfa/enroll")
@limiter.limit("5/minute")
def mfa_enroll(
    request: Request,
    current_user: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> MfaEnrollOut:
    """Begin TOTP enrollment. MFA stays disabled until confirmed with a valid code."""
    secret = generate_totp_secret()
    current_user.mfa_secret = secret
    current_user.mfa_enabled = False
    db.commit()
    return MfaEnrollOut(secret=secret, otpauth_uri=build_totp_uri(secret, current_user.username))


@router.post("/mfa/enroll/confirm")
@limiter.limit("5/minute")
def mfa_enroll_confirm(
    request: Request,
    body: MfaCodeIn,
    current_user: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if not current_user.mfa_secret or not verify_totp(current_user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    current_user.mfa_enabled = True
    db.commit()
    log_audit_event(
        db,
        event_type="mfa_enabled",
        actor=current_user.username,
        target=f"user/{current_user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"mfa_enabled": True}


@router.post("/mfa/disable")
@limiter.limit("5/minute")
def mfa_disable(
    request: Request,
    body: MfaCodeIn,
    current_user: User = Depends(require_role(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    if not current_user.mfa_enabled or not current_user.mfa_secret or not verify_totp(current_user.mfa_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    db.commit()
    log_audit_event(
        db,
        event_type="mfa_disabled",
        actor=current_user.username,
        target=f"user/{current_user.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
    )
    return {"mfa_enabled": False}


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
# Admin: per-integration API keys
#
# Replaces relying solely on the single static MONITOR_API_KEY (still
# accepted for backward compatibility) for automation clients — each
# integration gets its own revocable credential, capped at editor/viewer, so
# one compromised key doesn't require rotating the shared secret for
# everyone.
# ---------------------------------------------------------------------------

@router.post("/api-keys", status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
@limiter.limit("10/minute")
def create_api_key(
    request: Request,
    body: ApiKeyCreateIn,
    admin: User = Depends(require_role(Role.ADMIN)),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> ApiKeyCreatedOut:
    """Issue a new per-integration API key, scoped to one organization (the
    caller's org via X-Org-Id, or their sole membership). The plaintext is
    returned exactly once — only its hash and a short display prefix are
    stored."""
    raw_key = generate_api_key()
    row = ApiKey(
        org_id=ctx.org_id,
        name=body.name,
        key_hash=hash_token(raw_key),
        key_prefix=api_key_display_prefix(raw_key),
        role=body.role,
        created_by=admin.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_audit_event(
        db,
        event_type="api_key_created",
        actor=admin.username,
        target=f"api_key/{row.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"name": row.name, "role": row.role},
    )
    return ApiKeyCreatedOut(id=row.id, name=row.name, role=row.role, key_prefix=row.key_prefix, api_key=raw_key)


@router.get("/api-keys", dependencies=[Depends(require_role(Role.ADMIN))])
def list_api_keys(ctx: OrgContext = Depends(get_org_context), db: Session = Depends(get_db)) -> list[ApiKeyOut]:
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.org_id == ctx.org_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [ApiKeyOut.model_validate(r) for r in rows]


@router.delete("/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    request: Request,
    key_id: int,
    admin: User = Depends(require_role(Role.ADMIN)),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_db),
) -> None:
    row = db.query(ApiKey).filter(ApiKey.id == key_id, ApiKey.org_id == ctx.org_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    row.revoked = True
    row.revoked_at = utc_now()
    db.commit()
    log_audit_event(
        db,
        event_type="api_key_revoked",
        actor=admin.username,
        target=f"api_key/{row.id}",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        success=True,
        details={"name": row.name},
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


# ---------------------------------------------------------------------------
# Bootstrap: ensure a default organization exists on startup
#
# Covers the fresh-install path: migration 178fc3029731 only backfills a
# Default Organization when it finds existing users at migration time (an
# in-place upgrade of a populated single-tenant deployment). A brand-new
# install runs that migration with zero users, so there's nothing to
# backfill yet — this runs after ensure_default_admin() (which is what
# actually creates the first user) to cover that case too.
# ---------------------------------------------------------------------------

def ensure_default_organization(db: Session) -> None:
    if db.query(Organization).filter(Organization.slug == "default").one_or_none() is not None:
        return
    settings = get_settings()
    admin = db.query(User).filter(User.username == settings.admin_username).one_or_none()
    if admin is None:
        return
    org = Organization(name="Default Organization", slug="default", owner_user_id=admin.id)
    db.add(org)
    db.flush()
    db.add(OrgMembership(user_id=admin.id, org_id=org.id, role="owner", status="active"))
    db.commit()
    log.info("Default Organization created (owner: '%s').", admin.username)
