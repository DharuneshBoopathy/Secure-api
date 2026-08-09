from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.security import utc_now


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("slug", name="uq_org_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(128), index=True)
    # Denormalized pointer to the current primary owner for fast display
    # (org switcher, member lists). OrgMembership rows remain the source of
    # truth for access control — this is never read for authorization.
    owner_user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class OrgMembership(Base):
    """A user's role within one organization. status="pending" rows have no
    access until an owner approves them; "revoked" rows are kept (not
    deleted) so membership history survives removal."""

    __tablename__ = "org_memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnownEndpoint(Base):
    __tablename__ = "known_endpoints"
    __table_args__ = (UniqueConstraint("org_id", "method", "path_template", name="uq_known_method_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
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
        Index("ix_traffic_org_ts", "org_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
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
            "org_id",
            "method",
            "path_normalized",
            unique=True,
            mysql_length={"path_normalized": 191},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    method: Mapped[str] = mapped_column(String(16), index=True)
    path_normalized: Mapped[str] = mapped_column(String(1024), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    documented: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    alert_type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(256))
    detail: Mapped[str] = mapped_column(Text)
    method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    # The specific TrafficEvent this alert was raised from, when there is one
    # (traffic_anomaly / undocumented_api alerts). No FK, per this codebase's
    # existing no-FK-constraint convention. Lets feedback on an alert be
    # traced back to the exact training row for the ML retrain loop.
    event_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    # Top contributing features for anomaly alerts, e.g.
    # [{"feature": "query_entropy", "value": 5.1, "baseline_mean": 1.2, "z_score": 4.3}, ...]
    explanation: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    # Human feedback on whether this alert was a real finding, for the ML retrain loop.
    feedback: Mapped[str | None] = mapped_column(String(32), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OpenAPISnapshot(Base):
    __tablename__ = "openapi_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    title: Mapped[str] = mapped_column(String(256))
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # LONGTEXT on MySQL (specs routinely exceed TEXT's 64 KB limit), plain
    # TEXT everywhere else. The variant keeps the production DDL identical
    # while letting SQLite — used by the test suite and by the no-Docker
    # local-dev path — compile this table at all; LONGTEXT has no SQLite
    # rendering, so a bare LONGTEXT() fails at CREATE TABLE time there.
    raw_yaml: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))


class MLModelState(Base):
    """Versioned per-org model snapshots. Multiple rows per org are kept
    (bounded by MAX_MODEL_VERSIONS in ml_anomaly.py) so a bad retrain can be
    rolled back; exactly one row per org has is_active=True at a time, and
    that is the row load_model() uses for scoring."""

    __tablename__ = "ml_model_state"
    __table_args__ = (Index("ix_ml_model_org_active", "org_id", "is_active"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    sklearn_version: Mapped[str] = mapped_column(String(32))
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)


class ShadowEndpoint(Base):
    __tablename__ = "shadow_endpoints"
    __table_args__ = (
        Index(
            "ix_shadow_method_path",
            "org_id",
            "method",
            "path_normalized",
            unique=True,
            mysql_length={"path_normalized": 191},
        ),
        Index("ix_shadow_risk", "risk_score", "hit_count"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
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
    __table_args__ = (UniqueConstraint("org_id", "method", "path_template", name="uq_zombie_method_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
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
            "org_id",
            "day",
            "method",
            "path_normalized",
            unique=True,
            mysql_length={"path_normalized": 191},
        ),
        Index("ix_summary_day", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
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
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # TOTP secret is stored as soon as enrollment starts but mfa_enabled stays
    # False until the user proves possession by submitting one valid code —
    # otherwise a client-side error mid-enrollment could silently lock login.
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


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


class ApiKey(Base):
    """Per-integration API key. Replaces relying solely on the single static
    MONITOR_API_KEY for automation clients — each integration gets its own
    revocable credential and audit trail, capped at editor/viewer (never
    admin) since these are meant for unattended automation, not interactive
    account management."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # Stores the SHA-256 hex digest of the issued key, never the plaintext.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # First few characters of the plaintext key, kept for display/identification
    # in the admin UI so an operator can tell keys apart without ever seeing
    # the full secret again after creation.
    key_prefix: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(32), default="editor")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MonitoredApi(Base):
    """An upstream API onboarded by pasting its access key instead of a spec.

    Complements OpenAPISnapshot: that path suits an API you own and have a
    YAML file for, this one suits a third-party API (Claude, Gemini, OpenAI)
    where all you hold is a key. Either way the durable result is the same set
    of KnownEndpoint rows, so discovery / shadow / zombie / idle keep working
    unchanged — the endpoints seeded from a connection carry
    source="connection:<id>", which is also how they're found again when the
    connection is deleted.

    This is the only table holding a recoverable secret (see
    app/services/crypto.py for why, and for what happens when the encryption
    key rotates).
    """

    __tablename__ = "monitored_apis"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_monitored_api_org_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # Key into app.services.provider_catalog: "anthropic" | "openai" | "google" | "custom".
    provider: Mapped[str] = mapped_column(String(32), index=True)
    base_url: Mapped[str] = mapped_column(String(512))
    verify_path: Mapped[str] = mapped_column(String(512), default="/")
    # Fernet token, never the raw key. key_prefix/key_last4 are display-only,
    # mirroring ApiKey.key_prefix — enough to tell two keys apart, never
    # enough to use one.
    credential_ciphertext: Mapped[str] = mapped_column(Text)
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_last4: Mapped[str] = mapped_column(String(8), default="")
    endpoints_registered: Mapped[int] = mapped_column(Integer, default=0)
    # "unverified" | "active" | "invalid" | "error" — see app/services/provider_probe.py.
    status: Mapped[str] = mapped_column(String(16), default="unverified", index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (Index("ix_reset_user_used", "user_id", "used"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    # Stores the SHA-256 hex digest of the issued token, never the plaintext.
    token: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
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
