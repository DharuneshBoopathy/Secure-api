"""
Validates Task 3: Mounted-file secrets support via secrets_dir="/run/secrets".

Confirms that:
  1. Settings loads admin_password from a secrets-dir file when the env var is absent.
  2. Settings loads secret_key from a secrets-dir file.
  3. Settings loads monitor_api_key from a secrets-dir file.
  4. A value present in both the env and a secrets-dir file — env takes precedence
     (pydantic-settings resolution order: env > secrets file > default).
  5. The .env fallback is still honoured when no secrets dir or env var is present
     (local development parity).
  6. Settings.__config__ / model_config carries secrets_dir="/run/secrets".
  7. The secrets_dir does not need to exist at import time — missing dir is silently
     ignored by pydantic-settings (no startup crash).
"""


import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Helper: build a Settings-like class pointed at a tmp secrets dir
# ---------------------------------------------------------------------------

def _make_settings_class(secrets_dir: str, env_file: str = "/nonexistent/.env"):
    """Return a fresh Settings subclass using the given secrets_dir."""

    class _TestSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=env_file,
            env_file_encoding="utf-8",
            secrets_dir=secrets_dir,
            extra="ignore",
        )

        admin_password: str = "default-fallback"
        secret_key: str = "default-key"
        monitor_api_key: str = "default-monitor-key"

    return _TestSettings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_admin_password_loaded_from_secrets_file(tmp_path):
    secret_value = "super-secure-from-file-abc123XYZ"
    (tmp_path / "admin_password").write_text(secret_value)

    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.admin_password == secret_value


def test_secret_key_loaded_from_secrets_file(tmp_path):
    key = "a" * 32
    (tmp_path / "secret_key").write_text(key)

    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.secret_key == key


def test_monitor_api_key_loaded_from_secrets_file(tmp_path):
    api_key = "monitor-key-from-docker-secret"
    (tmp_path / "monitor_api_key").write_text(api_key)

    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.monitor_api_key == api_key


def test_env_var_takes_precedence_over_secrets_file(tmp_path, monkeypatch):
    """Environment variable wins over a secrets-dir file (pydantic-settings order)."""
    (tmp_path / "admin_password").write_text("from-file")
    monkeypatch.setenv("ADMIN_PASSWORD", "from-env-var")

    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.admin_password == "from-env-var"


def test_default_used_when_no_env_no_file(tmp_path):
    """When neither env var nor secret file is present, the field default is used."""
    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.admin_password == "default-fallback"


def test_missing_secrets_dir_does_not_crash():
    """A non-existent secrets_dir must not raise at construction time."""
    Cls = _make_settings_class("/run/secrets/this/does/not/exist")
    try:
        Cls()
    except Exception as exc:
        pytest.fail(f"Settings() raised unexpectedly with missing secrets_dir: {exc}")


def test_env_file_still_read_when_no_secrets_dir(tmp_path):
    """Local .env fallback works when secrets_dir is absent/empty."""
    env_file = tmp_path / ".env"
    env_file.write_text("ADMIN_PASSWORD=from-dotenv\n")

    Cls = _make_settings_class(str(tmp_path / "no-secrets"), env_file=str(env_file))
    s = Cls()
    assert s.admin_password == "from-dotenv"


def test_secrets_dir_configured_on_production_settings_class():
    """The real Settings class must declare secrets_dir='/run/secrets'."""
    from app.config import Settings

    cfg = Settings.model_config
    assert cfg.get("secrets_dir") == "/run/secrets", (
        "Settings.model_config must include secrets_dir='/run/secrets' "
        "for Kubernetes/Swarm mounted-secret support"
    )


def test_env_file_still_configured_on_production_settings_class():
    """The real Settings class must still declare env_file='.env' for local dev."""
    from app.config import Settings

    cfg = Settings.model_config
    assert cfg.get("env_file") == ".env", (
        "Settings.model_config must retain env_file='.env' for local development parity"
    )


def test_multiline_secret_file_stripped(tmp_path):
    """pydantic-settings trims trailing newlines from secret files automatically."""
    (tmp_path / "admin_password").write_text("clean-secret\n")

    Cls = _make_settings_class(str(tmp_path))
    s = Cls()
    assert s.admin_password == "clean-secret"
