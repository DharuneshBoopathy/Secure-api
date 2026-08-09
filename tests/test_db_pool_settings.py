"""
Connection pool configuration tests.

Covers:
  1. Settings expose DB_POOL_SIZE / DB_POOL_MAX_OVERFLOW / DB_POOL_TIMEOUT_SECONDS
     with sane, non-library-default values.
  2. app.database.engine is actually configured with those values (not left
     at SQLAlchemy's defaults of pool_size=5 / max_overflow=10).
"""

from app.config import Settings


def test_settings_expose_pool_config():
    s = Settings()
    assert s.db_pool_size == 10
    assert s.db_pool_max_overflow == 20
    assert s.db_pool_timeout_seconds == 30


def test_engine_pool_configured_explicitly():
    from app.database import engine

    pool = engine.pool
    assert pool.size() == 10
    assert pool._max_overflow == 20
    assert pool._timeout == 30
