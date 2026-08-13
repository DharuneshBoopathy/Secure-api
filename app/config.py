import logging
import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from app.services.secrets_provider import ExternalSecretsManagerSource

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets",
        env_ignore_empty=True,   # treat VAR= same as unset → default_factory runs
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Resolution order: env var > .env file > external secrets manager
        # (Vault/AWS/GCP, opt-in via SECRETS_PROVIDER) > /run/secrets/ file >
        # built-in default. A no-op source when SECRETS_PROVIDER is unset.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            ExternalSecretsManagerSource(settings_cls),
            file_secret_settings,
        )

    # "env" (default) = no external lookup. See app.services.secrets_provider
    # for supported values ("vault", "aws-secrets-manager", "gcp-secret-manager")
    # and the additional provider-specific env vars each one requires.
    secrets_provider: str = "env"
    # SQLAlchemy connection pool. Explicit rather than left at library
    # defaults (pool_size=5, max_overflow=10) so sizing is a deliberate,
    # documented choice per replica count — see the "Connection pooling"
    # section of the README. Total connections per replica ≈
    # db_pool_size + db_pool_max_overflow; keep replica_count * that figure
    # under your MySQL max_connections with headroom for admin/migration
    # connections.
    db_pool_size: int = 10
    db_pool_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30

    # Optional. None (default) = ingestion is processed synchronously in the
    # request handler, exactly as before this setting existed — the same
    # for slowapi's rate-limit storage (see app/routers/auth.py's Limiter).
    # Set to e.g. redis://redis:6379/0 to decouple /api/ingest/* from the
    # request path (see app/services/queue_service.py, app/worker.py) and
    # make rate limits correct across more than one API replica.
    redis_url: str | None = None

    # Set APP_ENV=production to enable strict secret validation at startup.
    # Any other value (including the default "development") enables dev mode:
    # missing secrets are auto-generated and printed to the log.
    app_env: str = "development"

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, v: object) -> str:
        # Accept any casing / stray whitespace, but reject unknown values
        # so typos like APP_ENV=Production silently downgrading to dev are
        # impossible.
        val = (str(v) if v is not None else "development").strip().lower()
        allowed = {"development", "staging", "production", "test"}
        if val not in allowed:
            raise ValueError(
                f"APP_ENV must be one of {sorted(allowed)}, got {v!r}"
            )
        return val

    # SQLite, so the default carries no credentials at all — neither a literal
    # password nor a conspicuously absent one. This is the same zero-setup path
    # the README documents for running without Docker; every real deployment
    # sets DATABASE_URL explicitly (docker-compose.yml, k8s/configmap.yaml),
    # and production refuses to start on this default — or on any SQLite URL —
    # because it is container-local and does not survive a restart. See
    # validate_security_settings, which tests provenance rather than truthiness
    # precisely because this default is non-empty.
    database_url: str = "sqlite:///./apimonitor.db"
    monitor_api_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    jwt_algorithm: str = "HS256"
    # ENCRYPTION_KEY encrypts third-party provider credentials stored in
    # `monitored_apis` (app/services/crypto.py). Accepts a Fernet key or any
    # sufficiently
    # random string. Unset derives one from SECRET_KEY, which is fine for a
    # single deployment — but rotating SECRET_KEY then makes saved provider
    # keys undecryptable and they have to be re-entered.
    encryption_key: str | None = None
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    admin_username: str = "admin"
    admin_password: str = Field(default_factory=lambda: secrets.token_urlsafe(24))
    # Per-account login lockout: after this many consecutive failed attempts
    # (independent of the per-IP slowapi limit on /auth/login), the account is
    # locked for an exponentially increasing duration.
    login_lockout_threshold: int = 5
    login_lockout_base_seconds: int = 30
    login_lockout_max_seconds: int = 900
    password_reset_token_expire_minutes: int = 30

    # Outbound email (app/services/mailer.py). Entirely optional: with
    # SMTP_HOST unset nothing is sent and password reset falls back to
    # administrator-assisted recovery. Set these to make self-service reset
    # work — without them a locked-out user has no way back in.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_use_starttls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 10
    # Origin used to build links in outbound mail, e.g. https://monitor.example.com.
    # Without it the reset message can only quote the bare token.
    public_base_url: str | None = None
    anomaly_threshold: float = 0.8
    ml_retrain_minutes: int = 15
    idle_threshold_hours: int = 24
    zombie_window_days: int = 30
    zombie_idle_threshold_days: int = 14
    zombie_dead_threshold_days: int = 30
    zombie_low_traffic_rpd: float = 1.0
    # Comma-separated origins for browser access (production UI + API on same host still works)
    cors_origins: str = ""
    # Set to true to mount the demo/debug router (development only — never enable in production)
    enable_demo: bool = False
    # Interactive API docs (/docs, /redoc, /openapi.json). Unauthenticated by
    # design in FastAPI, so on a monitoring tool they hand any visitor a
    # complete map of the API surface. Default off in production; set
    # EXPOSE_API_DOCS=true to re-enable deliberately.
    expose_api_docs: bool | None = None

    @property
    def api_docs_enabled(self) -> bool:
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.app_env != "production"
    # Opt-in only: when true, ?auth=<key|bearer> is accepted as a credential
    # source. Off by default because query strings are written to nginx /
    # proxy access logs, browser history, and Referer headers.
    allow_query_auth: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_cors_origins() -> list[str]:
    s = get_settings()
    extra = [x.strip() for x in s.cors_origins.split(",") if x.strip()]
    # In production only the explicitly configured origins are trusted; the
    # localhost defaults below would otherwise allow a dev server on the
    # operator's machine to make credentialed cross-origin requests to prod.
    if s.app_env == "production":
        seen: set[str] = set()
        out: list[str] = []
        for o in extra:
            if o not in seen:
                seen.add(o)
                out.append(o)
        if not out:
            log.warning(
                "CORS_ORIGINS is empty in production — the browser UI will "
                "only work when served from the same origin as the API."
            )
        return out

    defaults = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    seen = set()
    out = []
    for o in defaults + extra:
        if o not in seen:
            seen.add(o)
            out.append(o)
    return out


def validate_security_settings() -> None:
    """Validate secrets at startup.

    Development mode (APP_ENV != "production"):
        Auto-generated secrets are detected via pydantic's model_fields_set —
        any secret not present in env / .env / /run/secrets will have used its
        default_factory and therefore won't appear in model_fields_set.
        Those values are logged once in a visible banner so the developer can
        copy them into .env to persist across restarts.  Startup is not blocked.

    Production mode (APP_ENV=production):
        All secrets must be explicitly provided and must not use placeholder
        values.  Missing or weak secrets cause an immediate RuntimeError.
    """
    s = get_settings()

    if s.app_env != "production":
        # Fields that were not found in any external source (env var, .env file,
        # /run/secrets) will have fallen back to their default_factory and will
        # be absent from model_fields_set.
        _trackable = {
            "secret_key": "SECRET_KEY",  # nosec B105
            "monitor_api_key": "MONITOR_API_KEY",
            "admin_password": "ADMIN_PASSWORD",  # nosec B105
        }
        auto_generated = {
            env_name: getattr(s, field)
            for field, env_name in _trackable.items()
            if field not in s.model_fields_set
        }
        if auto_generated:
            lines = "\n".join(f"    {k}={v}" for k, v in auto_generated.items())
            log.warning(
                "\n"
                "  ┌──────────────────────────────────────────────────────────────┐\n"
                "  │  DEV MODE — auto-generated secrets (regenerated each restart) │\n"
                "  │  Add these to .env to persist across restarts:               │\n"
                "  ├──────────────────────────────────────────────────────────────┤\n"
                "%s\n"
                "  └──────────────────────────────────────────────────────────────┘",
                lines,
            )
        else:
            log.info("DEV MODE — all secrets loaded from environment / .env")
        return  # no hard checks in non-production

    # ── Production: strict enforcement ───────────────────────────────────────
    errors: list[str] = []
    # Checked by provenance, not truthiness. `database_url` has a non-empty
    # SQLite default, so an unset DATABASE_URL is never falsy here — it silently
    # resolves to a file inside the container. On a host with no persistent disk
    # (Render's free plan cannot attach one) that file is born empty on every
    # cold start, so the whole database — audit_log included — is discarded each
    # time the service wakes from a spin-down, while ensure_default_admin
    # recreates the admin account and makes the instance look healthy.
    #
    # Unset is an accident and stays fatal: nobody chose the fallback, and the
    # symptom is invisible from outside. An explicit sqlite:// URL is a
    # different thing — somebody typed it — so it warns loudly and boots. The
    # distinction is intent, not durability; both are equally ephemeral, which
    # is why the warning says so in as many words rather than hinting.
    if "database_url" not in s.model_fields_set or not s.database_url.strip():
        errors.append("DATABASE_URL is not set")
    elif s.database_url.startswith("sqlite"):
        log.warning(
            "\n"
            "  ┌──────────────────────────────────────────────────────────────┐\n"
            "  │  EPHEMERAL DATABASE — production is running on SQLite        │\n"
            "  ├──────────────────────────────────────────────────────────────┤\n"
            "  │  This file lives inside the container. Every restart, deploy │\n"
            "  │  and idle spin-down starts it empty: users, organizations,   │\n"
            "  │  traffic history and the audit log are all discarded, and    │\n"
            "  │  the bootstrap admin is recreated so nothing looks wrong.    │\n"
            "  │  Set DATABASE_URL to a durable database to keep any of it.   │\n"
            "  └──────────────────────────────────────────────────────────────┘\n"
            "  DATABASE_URL=%s",
            s.database_url,
        )
    if not s.monitor_api_key:
        errors.append("MONITOR_API_KEY is not set")
    if not s.secret_key or len(s.secret_key) < 32:
        errors.append("SECRET_KEY must be at least 32 characters")
    elif s.secret_key.startswith("change-me"):
        errors.append("SECRET_KEY must not use a placeholder value")
    if not s.admin_username:
        errors.append("ADMIN_USERNAME is not set")
    if not s.admin_password:
        errors.append("ADMIN_PASSWORD is not set")
    elif s.admin_password.startswith("change-me"):
        errors.append("ADMIN_PASSWORD must not use a placeholder value")
    if errors:
        raise RuntimeError(f"Refusing to start — insecure configuration: {'; '.join(errors)}")
