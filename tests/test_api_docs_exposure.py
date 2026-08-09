"""Interactive API docs must not be public in production.

FastAPI serves /docs, /redoc and /openapi.json with no authentication. On a
security-monitoring tool that hands any visitor the complete route map, so the
default flips with APP_ENV and can only be turned back on deliberately via
EXPOSE_API_DOCS.
"""

import pytest

from app.config import Settings


def _settings(**env) -> Settings:
    # Settings reads .env by default; _env_file=None isolates these from
    # whatever the developer has locally.
    return Settings(_env_file=None, **env)


def test_docs_enabled_by_default_in_development():
    assert _settings(app_env="development").api_docs_enabled is True


def test_docs_disabled_by_default_in_production():
    assert _settings(app_env="production").api_docs_enabled is False


@pytest.mark.parametrize("env", ["staging", "test"])
def test_docs_enabled_in_other_non_production_envs(env):
    assert _settings(app_env=env).api_docs_enabled is True


def test_explicit_opt_in_overrides_production_default():
    assert _settings(app_env="production", expose_api_docs=True).api_docs_enabled is True


def test_explicit_opt_out_overrides_development_default():
    assert _settings(app_env="development", expose_api_docs=False).api_docs_enabled is False


def test_app_omits_doc_routes_when_disabled(monkeypatch):
    """Guard the wiring, not just the flag: the FastAPI instance must actually
    drop the routes when the setting is off."""
    import importlib

    import app.config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXPOSE_API_DOCS", "false")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("MONITOR_API_KEY", "y" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD", "z" * 32)
    try:
        main_module = importlib.reload(importlib.import_module("app.main"))
        paths = {getattr(r, "path", None) for r in main_module.app.routes}
        assert "/docs" not in paths
        assert "/openapi.json" not in paths
    finally:
        # Restore the default-config app for the rest of the session.
        config_module.get_settings.cache_clear()
        for key in ("APP_ENV", "EXPOSE_API_DOCS", "SECRET_KEY", "MONITOR_API_KEY", "ADMIN_PASSWORD"):
            monkeypatch.delenv(key, raising=False)
        importlib.reload(importlib.import_module("app.main"))
