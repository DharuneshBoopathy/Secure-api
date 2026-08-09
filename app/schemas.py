from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# RFC 7231 + RFC 5789 verbs.  Restricting here means "<script>" / arbitrary
# 10MB strings can't reach the ORM slice-truncation.
HttpMethod = Literal[
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT",
]

# Ingest payload size caps.  These are defence-in-depth — the HTTP
# content-length middleware is the primary gate; these reject implausible
# values that escape it (e.g., size fields declared higher than the actual
# body).  2 GB is already well above any legitimate single request.
_MAX_BYTES = 2_000_000_000
_MAX_LATENCY_MS = 3_600_000  # 1 hour

# Upper bound on events-per-batch.  Protects against accidental OOM when a
# client sends a pathologically long array.
MAX_EVENTS_PER_BATCH = 10_000


class NginxAccessLog(BaseModel):
    """JSON access log line from nginx log_format (see nginx/nginx.conf)."""

    model_config = ConfigDict(extra="forbid")

    ts: str | None = Field(default=None, max_length=64)
    remote_addr: str | None = Field(default=None, max_length=64)
    method: HttpMethod
    uri: str = Field(max_length=1024)
    status: int = Field(ge=0, le=999)
    request_time: float | None = Field(default=None, ge=0.0, le=_MAX_LATENCY_MS / 1000.0)
    body_bytes_sent: int | None = Field(default=0, ge=0, le=_MAX_BYTES)
    auth: str | None = Field(default=None, max_length=2048)
    user_agent: str | None = Field(default=None, max_length=512)
    gateway: str | None = Field(default=None, max_length=64)


class IngestBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: HttpMethod
    path: str = Field(max_length=1024)
    status_code: int = Field(default=200, ge=0, le=999)
    latency_ms: float = Field(default=0.0, ge=0.0, le=_MAX_LATENCY_MS)
    client_ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
    auth_present: bool | None = None
    body_bytes: int = Field(default=0, ge=0, le=_MAX_BYTES)
    request_size_bytes: int = Field(default=0, ge=0, le=_MAX_BYTES)
    response_size_bytes: int = Field(default=0, ge=0, le=_MAX_BYTES)
    content_type: str | None = Field(default=None, max_length=128)
    x_forwarded_for: str | None = Field(default=None, max_length=256)
    referer: str | None = Field(default=None, max_length=512)
    monitor_key: str | None = Field(default=None, max_length=128)
    session_id: str | None = Field(default=None, max_length=256)
    gateway: str | None = Field(default="manual", max_length=64)
    raw_ref: str | None = Field(default=None, max_length=256)


class IngestBatch(BaseModel):
    events: list[IngestBatchItem] = Field(min_length=1, max_length=MAX_EVENTS_PER_BATCH)


class OpenAPIUpload(BaseModel):
    title: str = "Registered API"
    version: str | None = None
    spec_yaml: str


class PostmanUpload(BaseModel):
    title: str = "Registered API"
    collection_json: str


class CurlUpload(BaseModel):
    title: str = "Registered API"
    commands: str


class AlertOut(BaseModel):
    id: int
    created_at: datetime
    alert_type: str
    severity: str
    title: str
    detail: str
    method: str | None
    path: str | None
    acknowledged: bool
    event_id: int | None = None
    explanation: list[dict] | dict | None = None
    feedback: str | None = None
    feedback_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AlertFeedbackIn(BaseModel):
    label: Literal["true_positive", "false_positive"]


class MLModelVersionOut(BaseModel):
    id: int
    updated_at: datetime
    sklearn_version: str
    is_active: bool
    sample_count: int

    model_config = ConfigDict(from_attributes=True)


class DiscoveredOut(BaseModel):
    method: str
    path_normalized: str
    first_seen: datetime
    last_seen: datetime
    hit_count: int
    documented: bool

    model_config = ConfigDict(from_attributes=True)


class IdleEndpointOut(BaseModel):
    method: str
    path_template: str
    last_traffic: datetime | None
    hours_since_traffic: float | None


class StatsOut(BaseModel):
    events_last_hour: int
    discovered_undocumented: int
    open_alerts: int
    known_endpoints: int


class TrafficTrendPoint(BaseModel):
    """One day in the traffic-volume series. ``day`` is an ISO date string
    (YYYY-MM-DD) rather than a datetime — the series is day-granular and a
    timestamp would imply a precision the underlying rollup doesn't have."""

    day: str
    requests: int
    errors: int


class ShadowOut(BaseModel):
    id: int
    method: str
    path_normalized: str
    first_seen: datetime
    last_seen: datetime
    hit_count: int
    risk_score: int
    risk_level: str
    sample_ips: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    acknowledged: bool
    acknowledged_reason: str | None = None
    acknowledged_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ShadowAcknowledgeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=512)


class ZombieOut(BaseModel):
    id: int
    method: str
    path_template: str
    last_request_at: datetime | None
    requests_7d: int
    requests_14d: int
    requests_30d: int
    avg_daily_requests_30d: float
    status: str
    risk_level: str
    retired: bool
    retire_reason: str | None = None
    retired_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ZombieActionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=512)


class TrafficEventOut(BaseModel):
    id: int
    ts: datetime
    method: str
    path: str
    status_code: int
    source_ip: str | None = None
    response_time_ms: float
    request_size_bytes: int
    response_size_bytes: int
    user_agent: str | None = None
    content_type: str | None = None
    x_forwarded_for: str | None = None
    referer: str | None = None
    monitor_key: str | None = None
    session_id: str | None = None
    anomaly_score: float | None = None
    is_anomaly: bool
    anomaly_features: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    # Required only when the account has MFA enabled; a TOTP code is 6 digits
    # but the field is left slightly wider to tolerate whitespace-trimmed input.
    mfa_code: str | None = Field(default=None, min_length=6, max_length=10)


class MfaEnrollOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class RegisterIn(BaseModel):
    """Self-registration payload – new users default to 'viewer' role."""
    username: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    password: str = Field(min_length=12, max_length=256)
    email: str = Field(min_length=5, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminCreateUserIn(BaseModel):
    """Admin-only user creation – allows role assignment."""
    username: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    password: str = Field(min_length=12, max_length=256)
    email: str = Field(min_length=5, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="viewer", pattern=r"^(admin|editor|viewer)$")
    is_active: bool = True


class UserUpdateIn(BaseModel):
    """Admin-only user update – all fields optional."""
    email: str | None = Field(default=None, min_length=5, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str | None = Field(default=None, pattern=r"^(admin|editor|viewer)$")
    is_active: bool | None = None


class ChangePasswordIn(BaseModel):
    # current_password stays at 8 to accept legacy hashes; validate_password_strength
    # re-enforces the 12-char policy on new_password (defense-in-depth).
    current_password: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    mfa_enabled: bool = False

    model_config = ConfigDict(from_attributes=True)


class PasswordResetRequestIn(BaseModel):
    email: str = Field(min_length=5, max_length=256, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=3, max_length=128)
    # Capped below admin — these are for unattended automation clients, not
    # interactive account management.
    role: str = Field(default="editor", pattern=r"^(editor|viewer)$")


class ApiKeyCreatedOut(BaseModel):
    id: int
    name: str
    role: str
    key_prefix: str
    api_key: str  # plaintext — shown exactly once, at creation


class ApiKeyOut(BaseModel):
    id: int
    name: str
    role: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool
    revoked_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    owner_user_id: int
    created_at: datetime
    my_role: str | None = None

    model_config = ConfigDict(from_attributes=True)


class OrgRenameIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)


class OrgTransferOwnershipIn(BaseModel):
    new_owner_user_id: int


class OrgMembershipOut(BaseModel):
    id: int
    user_id: int
    username: str
    org_id: int
    role: str
    status: str
    created_at: datetime
    decided_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class OrgMembershipRoleIn(BaseModel):
    role: str = Field(pattern=r"^(owner|editor|viewer)$")


class TokenRefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10)


class AuthOut(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserOut


class AuditOut(BaseModel):
    id: int
    event_type: str
    actor: str
    target: str | None
    ip: str | None
    user_agent: str | None
    timestamp: datetime
    details: dict[str, Any] = Field(default_factory=dict)
    success: bool

    model_config = ConfigDict(from_attributes=True)


# --- Key-based API onboarding (app/routers/connections.py) -------------------

class ProviderOut(BaseModel):
    """One entry of the built-in provider catalog, for populating the UI's
    provider picker — key format hints and endpoint counts come from the
    server so the two never drift."""

    id: str
    label: str
    base_url: str
    key_hint: str
    docs_url: str | None
    endpoint_count: int
    requires_base_url: bool


class ConnectedApiCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(max_length=32)
    name: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=8, max_length=512)
    # Custom provider only; ignored for catalog providers, whose base URL and
    # verify path are fixed so a saved connection can't be pointed elsewhere.
    base_url: str | None = Field(default=None, max_length=512)
    verify_path: str | None = Field(default=None, max_length=512)
    # Custom provider only: newline-separated "METHOD /path" lines.
    endpoints: str | None = Field(default=None, max_length=20_000)
    # Probe the provider during creation. Off = save now, verify later.
    verify: bool = True


class ConnectedApiOut(BaseModel):
    id: int
    name: str
    provider: str
    provider_label: str
    base_url: str
    key_masked: str
    endpoints_registered: int
    status: str
    last_checked_at: datetime | None
    last_check_detail: str | None
    created_at: datetime
