"""
External secrets-manager integration tests (app.services.secrets_provider,
plus the Settings.settings_customise_sources wiring in app.config).

Covers:
  1. SECRETS_PROVIDER unset/"env" — the external source contributes nothing.
  2. An unrecognized SECRETS_PROVIDER value degrades to None (no crash).
  3. Missing SDK for each provider raises a RuntimeError naming the pip package.
  4. resolve_secret() swallows fetch failures and returns None rather than raising.
  5. resolve_secret() returns the right field from a mocked provider blob.
  6. End-to-end: a real Settings subclass picks up a value from a mocked
     external provider when no env var / .env value is present.
  7. End-to-end: an explicit env var still outranks the external provider.
  8. The blob fetch is cached per provider (only fetched once across two field lookups).
"""

from unittest.mock import patch

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.secrets_provider import (
    ExternalSecretsManagerSource,
    _fetch_from_aws,
    _fetch_from_gcp,
    _fetch_from_vault,
    _fetch_secret_blob,
    resolve_secret,
)


@pytest.fixture(autouse=True)
def _clear_blob_cache():
    _fetch_secret_blob.cache_clear()
    yield
    _fetch_secret_blob.cache_clear()


def _make_settings_class(env_file: str = "/nonexistent/.env"):
    class _TestSettings(BaseSettings):
        model_config = SettingsConfigDict(env_file=env_file, secrets_dir="/nonexistent-secrets", extra="ignore")

        secret_key: str = "default-key"
        admin_password: str = "default-admin-password"
        monitor_api_key: str = "default-monitor-key"

        @classmethod
        def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
            return (init_settings, env_settings, dotenv_settings, ExternalSecretsManagerSource(settings_cls), file_secret_settings)

    return _TestSettings


def test_provider_unset_contributes_nothing(monkeypatch):
    monkeypatch.delenv("SECRETS_PROVIDER", raising=False)
    Cls = _make_settings_class()
    s = Cls()
    assert s.secret_key == "default-key"


def test_unrecognized_provider_degrades_to_none(monkeypatch):
    monkeypatch.setenv("SECRETS_PROVIDER", "not-a-real-provider")
    Cls = _make_settings_class()
    s = Cls()  # must not raise
    assert s.secret_key == "default-key"


def test_vault_missing_sdk_raises_with_install_hint():
    with pytest.raises(RuntimeError, match="pip install hvac"):
        _fetch_from_vault()


def test_aws_missing_sdk_raises_with_install_hint():
    with pytest.raises(RuntimeError, match="pip install boto3"):
        _fetch_from_aws()


def test_gcp_missing_sdk_raises_with_install_hint():
    with pytest.raises(RuntimeError, match="pip install google-cloud-secret-manager"):
        _fetch_from_gcp()


def test_resolve_secret_swallows_failures(monkeypatch):
    monkeypatch.delenv("VAULT_ADDR", raising=False)
    monkeypatch.delenv("VAULT_TOKEN", raising=False)
    monkeypatch.delenv("VAULT_SECRET_PATH", raising=False)
    # hvac isn't installed and Vault env vars aren't set — either failure
    # mode must resolve to None, never raise.
    assert resolve_secret("vault", "secret_key") is None


def test_resolve_secret_returns_mocked_field():
    with patch(
        "app.services.secrets_provider._fetch_secret_blob",
        return_value={"secret_key": "from-mock-provider"},
    ):
        assert resolve_secret("vault", "secret_key") == "from-mock-provider"
        assert resolve_secret("vault", "admin_password") is None


def test_settings_picks_up_value_from_mocked_provider(monkeypatch):
    monkeypatch.setenv("SECRETS_PROVIDER", "vault")
    with patch(
        "app.services.secrets_provider._fetch_secret_blob",
        return_value={"secret_key": "provider-supplied-key"},
    ):
        Cls = _make_settings_class()
        s = Cls()
    assert s.secret_key == "provider-supplied-key"
    # Fields the mocked blob doesn't contain still fall through to default.
    assert s.admin_password == "default-admin-password"


def test_env_var_outranks_external_provider(monkeypatch):
    monkeypatch.setenv("SECRETS_PROVIDER", "vault")
    monkeypatch.setenv("SECRET_KEY", "from-env-var")
    with patch(
        "app.services.secrets_provider._fetch_secret_blob",
        return_value={"secret_key": "from-provider"},
    ):
        Cls = _make_settings_class()
        s = Cls()
    assert s.secret_key == "from-env-var"


def test_blob_fetch_cached_across_field_lookups():
    with patch(
        "app.services.secrets_provider._fetch_from_vault",
        return_value={"secret_key": "x", "admin_password": "y", "monitor_api_key": "z"},
    ) as mock_fetch:
        resolve_secret("vault", "secret_key")
        resolve_secret("vault", "admin_password")
    assert mock_fetch.call_count == 1
