import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
import re

import bcrypt as _bcrypt
import jwt

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
