import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_pool_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    echo=False,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_database(*, attempts: int = 10, delay: float = 2.0) -> None:
    """
    Block until the database accepts a connection or the attempt limit is reached.
    Called once at application startup before any DDL so that a slow MySQL
    initialisation never causes a crash-loop.
    """
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            log.info("Database is ready (attempt %d/%d)", attempt, attempts)
            return
        except OperationalError as exc:
            if attempt == attempts:
                raise
            log.warning(
                "Database not ready yet (attempt %d/%d): %s — retrying in %.0f s",
                attempt, attempts, exc, delay,
            )
            time.sleep(delay)
