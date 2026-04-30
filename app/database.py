import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)

settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
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


def ensure_phase1_schema() -> None:
    """
    Lightweight compatibility migrations for local/prototype environments.
    Keeps existing installs running without requiring Alembic.
    Retries up to 10 times (2 s apart) to handle the brief window between
    MySQL accepting TCP connections and being ready for DDL.
    """
    for attempt in range(1, 11):
        try:
            _apply_phase1_schema()
            return
        except OperationalError as exc:
            if attempt == 10:
                raise
            log.warning(
                "Schema migration not ready (attempt %d/10): %s — retrying in 2 s",
                attempt, exc,
            )
            time.sleep(2)


def _apply_phase1_schema() -> None:
    insp = inspect(engine)
    if "traffic_events" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns("traffic_events")}
    ddl: list[str] = []
    if "response_time_ms" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN response_time_ms FLOAT DEFAULT 0")
    if "source_ip" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN source_ip VARCHAR(64) NULL")
    if "request_size_bytes" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN request_size_bytes INTEGER DEFAULT 0")
    if "response_size_bytes" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN response_size_bytes INTEGER DEFAULT 0")
    if "content_type" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN content_type VARCHAR(128) NULL")
    if "x_forwarded_for" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN x_forwarded_for VARCHAR(256) NULL")
    if "referer" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN referer VARCHAR(512) NULL")
    if "monitor_key" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN monitor_key VARCHAR(128) NULL")
    if "session_id" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN session_id VARCHAR(256) NULL")
    if "is_anomaly" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN is_anomaly BOOLEAN DEFAULT 0")
    if "anomaly_features" not in existing:
        ddl.append("ALTER TABLE traffic_events ADD COLUMN anomaly_features JSON NULL")
    with engine.begin() as conn:
        for sql in ddl:
            conn.execute(text(sql))
