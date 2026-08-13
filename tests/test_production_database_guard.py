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

These tests pin the guard to provenance rather than truthiness, and pin the
intent split: an unset DATABASE_URL is fatal because nobody chose the fallback,
while an explicit sqlite:// URL boots with a warning that names what it costs.
"""

import logging

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


def test_explicit_sqlite_url_boots_with_a_warning(caplog):
    """An explicit sqlite:// URL is an operator decision, not the silent
    fallback, so it is allowed — but it is no more durable, so the warning has
    to name the consequence rather than hint at it."""
    settings = _settings(database_url="sqlite:////tmp/apimonitor.db")

    with caplog.at_level(logging.WARNING, logger="app.config"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.config.get_settings", lambda: settings)
            validate_security_settings()  # must not raise

    warning = caplog.text
    assert "EPHEMERAL DATABASE" in warning
    assert "audit log" in warning
    # The operator has to be able to see which path is in play.
    assert "sqlite:////tmp/apimonitor.db" in warning


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


def test_unset_and_explicit_sqlite_are_treated_differently(caplog):
    """The whole point of the provenance check: the same resolved value is
    fatal when nobody chose it and permitted when somebody did."""
    default = _settings()
    explicit = _settings(database_url=default.database_url)
    assert default.database_url == explicit.database_url, "same value either way"

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.config.get_settings", lambda: default)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
            validate_security_settings()

    with caplog.at_level(logging.WARNING, logger="app.config"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("app.config.get_settings", lambda: explicit)
            validate_security_settings()  # must not raise

    assert "EPHEMERAL DATABASE" in caplog.text
