import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
import re

import bcrypt as _bcrypt
import jwt
import pyotp

from app.config import get_settings


def utc_now() -> datetime:
    """Return the current UTC time as a naive datetime.

    Replacement for the deprecated ``datetime.utcnow()`` that avoids the
    deprecation warning while remaining compatible with the MySQL/SQLite
    backends which store naive (tz-unaware) timestamps.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Role enum – three-tier RBAC
# ---------------------------------------------------------------------------
class Role(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"

    @classmethod
    def has_value(cls, value: str) -> bool:
        return value in cls._value2member_map_

    def level(self) -> int:
        """Higher level = more privilege."""
        return {Role.VIEWER: 0, Role.EDITOR: 1, Role.ADMIN: 2}[self]

    def __ge__(self, other: "Role") -> bool:  # type: ignore[override]
        return self.level() >= other.level()

    def __gt__(self, other: "Role") -> bool:  # type: ignore[override]
        return self.level() > other.level()

    def __le__(self, other: "Role") -> bool:  # type: ignore[override]
        return self.level() <= other.level()

    def __lt__(self, other: "Role") -> bool:  # type: ignore[override]
        return self.level() < other.level()


# ---------------------------------------------------------------------------
# Org role enum – three-tier per-organization RBAC (distinct from the
# platform-level Role above; see docs/adr/002-multi-tenancy-schema.md)
# ---------------------------------------------------------------------------
class OrgRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    @classmethod
    def has_value(cls, value: str) -> bool:
        return value in cls._value2member_map_

    def level(self) -> int:
        return {OrgRole.VIEWER: 0, OrgRole.EDITOR: 1, OrgRole.OWNER: 2}[self]

    def __ge__(self, other: "OrgRole") -> bool:  # type: ignore[override]
        return self.level() >= other.level()

    def __gt__(self, other: "OrgRole") -> bool:  # type: ignore[override]
        return self.level() > other.level()

    def __le__(self, other: "OrgRole") -> bool:  # type: ignore[override]
        return self.level() <= other.level()

    def __lt__(self, other: "OrgRole") -> bool:  # type: ignore[override]
        return self.level() < other.level()


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------
class PasswordValidationError(ValueError):
    """Raised when a password does not meet the policy."""


def validate_password_strength(password: str) -> None:
    """Enforce strong password policy: min 12 chars, upper, lower, digit, special."""
    errors: list[str] = []
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        errors.append("Password must contain at least one special character")
    if errors:
        raise PasswordValidationError("; ".join(errors))


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


# Module-level constant so we run gensalt exactly once at import time rather
# than on every timing-equalizer call.  Value is a valid bcrypt hash of a
# string that no password check will ever match.
DUMMY_PASSWORD_HASH: str = _bcrypt.hashpw(
    b"__timing_anchor__", _bcrypt.gensalt()
).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return _bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


API_KEY_PREFIX = "amk_"  # "api monitor key" — helps secret scanners flag leaked keys

# How long an SSE stream ticket stays valid. Only has to cover the round trip
# between minting the ticket and opening the EventSource, so it is deliberately
# far shorter than an access token — the whole point is that a ticket found in
# a log is almost certainly already expired.
STREAM_TICKET_TTL_SECONDS = 60


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def api_key_display_prefix(raw_key: str) -> str:
    """First few characters kept for display after creation — never enough
    to reconstruct or brute-force the rest of the key."""
    return raw_key[: len(API_KEY_PREFIX) + 8]


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token string.

    Used to store refresh tokens as hashes so that a database dump cannot be
    used to replay sessions.  The digest is 64 hex characters; the original
    JWT is never written to persistent storage.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(subject: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires = utc_now() + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {"sub": subject, "type": "access", "exp": expires}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires


def create_stream_ticket(subject: str, org_id: int) -> tuple[str, int]:
    """Mint a short-lived, single-purpose credential for the SSE endpoints.

    EventSource cannot send an Authorization header, so a browser opening a
    stream has no way to present a normal bearer token — which is why the
    stream URLs used to carry the full access token as a query parameter, and
    why that token then appeared verbatim in every access log along the path.

    A ticket exists to bound that exposure rather than eliminate it: it is
    valid for a minute, and its distinct ``type`` means the REST API refuses
    it, so a ticket recovered from a log is worth far less than the access
    token it replaces.

    The organization is baked in at mint time. EventSource can't send the
    X-Org-Id header either, so without this the stream would fall back to
    "the caller's only membership" and simply 400 for anyone who belongs to
    more than one org.
    """
    settings = get_settings()
    expires = utc_now() + timedelta(seconds=STREAM_TICKET_TTL_SECONDS)
    payload: dict[str, Any] = {"sub": subject, "type": "stream", "org": org_id, "exp": expires}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, STREAM_TICKET_TTL_SECONDS


def create_refresh_token(subject: str) -> tuple[str, datetime]:
    settings = get_settings()
    expires = utc_now() + timedelta(days=settings.refresh_token_expire_days)
    # jti (JWT ID) is a random nonce that makes every token unique even when two tokens
    # are issued within the same clock second.  Without it, same-second tokens produce
    # identical JWTs (PyJWT truncates exp to integer seconds), which would break the
    # rotation-based replay-protection mechanism.
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "refresh",
        "exp": expires,
        "jti": secrets.token_hex(16),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


# ---------------------------------------------------------------------------
# TOTP-based MFA (RFC 6238)
# ---------------------------------------------------------------------------

MFA_ISSUER = "API Security Monitor"


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, username: str) -> str:
    """otpauth:// URI for QR-code provisioning in an authenticator app."""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=MFA_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    """Accept the current code plus one 30s step of clock drift either way."""
    try:
        return pyotp.totp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False
