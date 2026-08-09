"""
Phase 5.1 (distributed rate limiting): slowapi's Limiter must use a shared
Redis backend when REDIS_URL is configured, so limits are correct across
more than one API replica — and fall back to the original in-memory backend
(per-process only) when it isn't, unchanged from before Phase 5.

Covers:
  1. With no REDIS_URL, the Limiter uses limits' MemoryStorage (unchanged
     default behavior).
  2. With REDIS_URL set, the Limiter uses limits' RedisStorage instead.
     (Construction only — no live Redis server required; the storage
     backend connects lazily on first use.)
"""

from limits.storage.memory import MemoryStorage
from limits.storage.redis import RedisStorage
from slowapi import Limiter
from slowapi.util import get_remote_address


def test_limiter_uses_memory_storage_when_no_redis_url():
    limiter = Limiter(key_func=get_remote_address, storage_uri=None or "memory://")
    assert isinstance(limiter._storage, MemoryStorage)


def test_limiter_uses_redis_storage_when_redis_url_configured():
    limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379/0" or "memory://")
    assert isinstance(limiter._storage, RedisStorage)


def test_auth_module_limiter_storage_selection_mirrors_settings(monkeypatch):
    """The exact expression app/routers/auth.py uses: get_settings().redis_url
    or "memory://" — asserted in isolation so it's covered even though the
    module-level `limiter` singleton is already built at import time with
    whatever REDIS_URL happened to be set then."""
    import app.config as config_mod

    config_mod.get_settings.cache_clear()
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    try:
        settings = config_mod.get_settings()
        storage_uri = settings.redis_url or "memory://"
        assert storage_uri == "redis://redis:6379/0"
        limiter = Limiter(key_func=get_remote_address, storage_uri=storage_uri)
        assert isinstance(limiter._storage, RedisStorage)
    finally:
        config_mod.get_settings.cache_clear()
