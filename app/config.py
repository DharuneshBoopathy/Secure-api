import logging
import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir="/run/secrets",
        env_ignore_empty=True,   # treat VAR= same as unset → default_factory runs
        extra="ignore",
    )

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

    database_url: str = "mysql+pymysql://apimonitor:apimonitor_secret@127.0.0.1:3306/apimonitor"
    monitor_api_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    admin_username: str = "admin"
    admin_password: str = Field(default_factory=lambda: secrets.token_urlsafe(24))
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
    seen: set[str] = set()
    out: list[str] = []
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
            "secret_key": "SECRET_KEY",
            "monitor_api_key": "MONITOR_API_KEY",
            "admin_password": "ADMIN_PASSWORD",
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
    if not s.database_url:
        errors.append("DATABASE_URL is not set")
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
