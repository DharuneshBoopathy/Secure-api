"""Reversible encryption for third-party provider credentials at rest.

Every other secret this app stores is one-way hashed — bcrypt for passwords,
``app.security.hash_token`` (SHA-256) for issued API keys and refresh tokens —
because the app only ever needs to *verify* those. Provider keys held in
``monitored_apis`` are the one exception: to probe a connection the monitor has
to replay the operator's key against Anthropic / OpenAI / Google, so it must be
able to get the plaintext back.

That makes this module the only place recoverable secrets live, so it is kept
deliberately narrow: Fernet (AES-128-CBC + HMAC-SHA256, authenticated) over a
key resolved from ``ENCRYPTION_KEY``, falling back to one derived from
``SECRET_KEY``. Nothing else in the codebase should encrypt with it.

Operational note: with ``ENCRYPTION_KEY`` unset, rotating ``SECRET_KEY``
(including the dev-mode auto-generated one, which changes every restart)
invalidates every stored credential. That is why decryption failure is a
recoverable, typed error — the UI surfaces "re-enter the key" rather than a
500.
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class DecryptionError(RuntimeError):
    """Stored ciphertext could not be decrypted with the current key."""


def _fernet_key_from_passphrase(passphrase: str) -> bytes:
    """Stretch an arbitrary string into the 32-byte urlsafe-base64 key Fernet
    requires, so operators can set APP_ENCRYPTION_KEY to any sufficiently
    random string rather than having to run Fernet.generate_key() first."""
    return base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    configured = (settings.encryption_key or "").strip()
    if configured:
        try:
            # A real Fernet key (44-char urlsafe base64) is used verbatim so
            # keys generated with Fernet.generate_key() work as-is.
            return Fernet(configured.encode())
        except (ValueError, TypeError):
            return Fernet(_fernet_key_from_passphrase(configured))
    # Domain-separated from any other use of SECRET_KEY (JWT signing) so the
    # two never derive the same bytes.
    return Fernet(_fernet_key_from_passphrase(f"monitored-api-credentials:{settings.secret_key}"))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as e:
        raise DecryptionError(
            "Stored credential could not be decrypted — the encryption key changed "
            "since it was saved. Re-enter the key to fix this."
        ) from e


def mask_secret(plaintext: str, *, prefix_len: int = 8, suffix_len: int = 4) -> tuple[str, str]:
    """Split a credential into the display-only (prefix, last4) pair persisted
    alongside the ciphertext, mirroring ``ApiKey.key_prefix``: enough for an
    operator to tell two keys apart, never enough to use one."""
    key = plaintext.strip()
    return key[:prefix_len], key[-suffix_len:] if len(key) > prefix_len + suffix_len else ""
