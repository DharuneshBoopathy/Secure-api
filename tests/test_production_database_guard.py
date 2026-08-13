"""
Production DATABASE_URL guard.

`Settings.database_url` defaults to "sqlite:///./apimonitor.db" so the app can
run with no setup at all. That default is non-empty, which made the original
production check — `if not s.database_url` — unreachable: an unset DATABASE_URL
resolved to a container-local SQLite file and the service booted happily on it.

On a host with no persistent disk that file starts empty after every restart, so
the entire database is discarded while ensure_default_admin recreates the admin
account and the instance still looks healthy. The audit log is the most
conspicuous casualty, and the least acceptable one for a security product.

These tests pin the guard to provenance and dialect rather than truthiness.
"""

import pytest

from app.config import Settings, validate_security_settings

STRONG = "x" * 40


def _settings(**overrides) -> Settings:
    """A Settings instance that passes every production check except the one
    under test. Built with explicit kwargs so model_fields_set is populated
    exactly as it would be from real environment variables."""
    base = dict(
        app_env="production",
        monitor_api_key=STRONG,
        secret_key=STRONG,
        admin_username="dharunesh",
        admin_password=STRONG,
    )
    base.update(overrides)
    # _env_file=None keeps a developer's local .env out of the fixture; without
    # it these assertions would pass or fail based on the machine they run on.
    return Settings(_env_file=None, **base)


@pytest.fixture
def patched(monkeypatch):
    def _apply(settings: Settings) -> None:
        monkeypatch.setattr("app.config.get_settings", lambda: settings)

    return _apply


def test_unset_database_url_refuses_to_start(patched):
    """The default is non-empty, so this is the case the old check missed."""
    s = _settings()
    assert s.database_url.startswith("sqlite"), "fixture assumption: default is SQLite"
    patched(s)

    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        validate_security_settings()


def test_explicit_sqlite_url_refuses_to_start(patched):
    """Setting DATABASE_URL to SQLite on purpose is no more durable than
    leaving it unset, so it is rejected too — with a message that says why."""
    patched(_settings(database_url="sqlite:///./apimonitor.db"))

    with pytest.raises(RuntimeError, match="lost on every restart"):
        validate_security_settings()


def test_blank_database_url_refuses_to_start(patched):
    """env_ignore_empty=True rewrites DATABASE_URL= to unset before it reaches
    the model, but that only covers the env sources. A blank value arriving any
    other way is still explicitly set, so provenance alone would wave it
    through — hence the emptiness check alongside it."""
    patched(_settings(database_url="   "))

    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        validate_security_settings()


def test_mysql_url_starts_normally(patched):
    patched(_settings(database_url="mysql+pymysql://user:pw@db.example.com:3306/apimonitor"))

    validate_security_settings()  # must not raise


def test_guard_is_production_only(patched):
    """Development keeps the zero-setup SQLite path the README documents."""
    patched(_settings(app_env="development"))

    validate_security_settings()  # must not raise


def test_sqlite_error_names_the_variable_and_the_consequence(patched):
    """The failure is only useful if the operator can act on it without
    reading the source."""
    patched(_settings(database_url="sqlite:///./apimonitor.db"))

    with pytest.raises(RuntimeError) as exc:
        validate_security_settings()

    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "SQLite" in message
