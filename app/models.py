from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.security import utc_now


class KnownEndpoint(Base):
    __tablename__ = "known_endpoints"
    __table_args__ = (UniqueConstraint("method", "path_template", name="uq_known_method_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_template: Mapped[str] = mapped_column(String(512), index=True)
    source: Mapped[str] = mapped_column(String(64), default="openapi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_traffic_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class TrafficEvent(Base):
    __tablename__ = "traffic_events"
    # utf8mb4 index bytes: full VARCHAR(1024) exceeds InnoDB 3072-byte key limit; use prefix indexes.
    __table_args__ = (
        Index("ix_traffic_events_path", "path", mysql_length=191),
        Index("ix_traffic_method_path_ts", "method", "path", "ts", mysql_length={"path": 191}),
        # Accelerates the 30-day zombie scanner which filters by is_documented then orders by ts.
        Index("ix_traffic_doc_ts", "is_documented", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True, default=utc_now)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    response_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    x_forwarded_for: Mapped[str | None] = mapped_column(String(256), nullable=True)
    referer: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_present: Mapped[bool] = mapped_column(Boolean, default=False)
    body_bytes: Mapped[int] = mapped_column(Integer, default=0)
    request_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    response_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    gateway: Mapped[str | None] = mapped_column(String(64), nullable=True)
    monitor_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    raw_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_documented: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_features: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DiscoveredEndpoint(Base):
    __tablename__ = "discovered_endpoints"
    __table_args__ = (
        Index(
            "uq_disc_method_path",
            "method",
            "path_normalized",
            unique=True,
            mysql_length={"path_normalized": 191},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_normalized: Mapped[str] = mapped_column(String(1024), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    documented: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)


class OpenAPISnapshot(Base):
    __tablename__ = "openapi_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    title: Mapped[str] = mapped_column(String(256))
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_yaml: Mapped[str] = mapped_column(LONGTEXT)


class MLModelState(Base):
    __tablename__ = "ml_model_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    sklearn_version: Mapped[str] = mapped_column(String(32))
    blob: Mapped[bytes] = mapped_column(LargeBinary)


class ShadowEndpoint(Base):
    __tablename__ = "shadow_endpoints"
    __table_args__ = (
        Index("ix_shadow_method_path", "method", "path_normalized", unique=True, mysql_length={"path_normalized": 191}),
        Index("ix_shadow_risk", "risk_score", "hit_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_normalized: Mapped[str] = mapped_column(String(1024), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, default=1, index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    sample_ips: Mapped[list | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ZombieEndpointState(Base):
    __tablename__ = "zombie_endpoint_state"
    __table_args__ = (UniqueConstraint("method", "path_template", name="uq_zombie_method_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_template: Mapped[str] = mapped_column(String(512), index=True)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    requests_7d: Mapped[int] = mapped_column(Integer, default=0)
    requests_14d: Mapped[int] = mapped_column(Integer, default=0)
    requests_30d: Mapped[int] = mapped_column(Integer, default=0)
    avg_daily_requests_30d: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="LOW", index=True)
    retired: Mapped[bool] = mapped_column(Boolean, default=False)
    retire_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TrafficDailySummary(Base):
    __tablename__ = "traffic_daily_summary"
    __table_args__ = (
        Index(
            "uq_summary_day_method_path",
            "day",
            "method",
            "path_normalized",
            unique=True,
            mysql_length={"path_normalized": 191},
        ),
        Index("ix_summary_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day: Mapped[datetime] = mapped_column(DateTime, index=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_normalized: Mapped[str] = mapped_column(String(1024), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_user_username"),
        UniqueConstraint("email", name="uq_user_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), index=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_user_revoked", "user_id", "revoked"),
        Index("ix_refresh_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # Stores the SHA-256 hex digest of the issued JWT (64 chars), never the plaintext token.
    token: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_event_ts", "event_type", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
