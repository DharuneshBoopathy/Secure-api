"""Optional external secrets-manager integration.

Local/Docker/Swarm/K8s deployments are already covered by
``app.config.Settings`` (env var -> .env file -> /run/secrets/ mounted file
-> default). Set ``SECRETS_PROVIDER`` to instead pull ``SECRET_KEY``,
``ADMIN_PASSWORD``, and ``MONITOR_API_KEY`` from a real secrets manager, so
they can be rotated without a redeploy.

Supported values for ``SECRETS_PROVIDER``:
  - "env" (default) — no external lookup; existing resolution order applies.
  - "vault" — HashiCorp Vault KV v2. Requires ``pip install hvac`` and
    ``VAULT_ADDR`` / ``VAULT_TOKEN`` / ``VAULT_SECRET_PATH``.
  - "aws-secrets-manager" — AWS Secrets Manager. Requires
    ``pip install boto3`` and ``AWS_SECRETS_MANAGER_SECRET_ID`` (plus
    standard AWS credential resolution; optionally ``AWS_REGION``).
  - "gcp-secret-manager" — GCP Secret Manager. Requires
    ``pip install google-cloud-secret-manager`` and ``GCP_SECRET_PROJECT`` /
    ``GCP_SECRET_ID``.

Each provider is expected to hold ONE secret containing a JSON object keyed
by the field names, e.g.::

    {"secret_key": "...", "admin_password": "...", "monitor_api_key": "..."}

This keeps rotation atomic (one write updates all three) and avoids needing
a separate path/secret-id per field. The corresponding cloud SDKs are
intentionally NOT hard dependencies of this project (most deployments run on
a single box and never need them) — install whichever one you use.
"""

from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource

log = logging.getLogger(__name__)

EXTERNAL_SECRET_FIELDS = ("secret_key", "admin_password", "monitor_api_key")


@functools.lru_cache
def _fetch_secret_blob(provider: str) -> dict[str, str]:
    """Fetch (and cache for the process lifetime) the JSON secret blob."""
    if provider == "vault":
        return _fetch_from_vault()
    if provider == "aws-secrets-manager":
        return _fetch_from_aws()
    if provider == "gcp-secret-manager":
        return _fetch_from_gcp()
    raise ValueError(f"Unknown SECRETS_PROVIDER: {provider!r}")


def resolve_secret(provider: str, field_name: str) -> str | None:
    """Best-effort lookup of one field from the external provider's blob.

    Failures are logged and degrade to None (falling through to the next
    settings source: /run/secrets/ then the built-in default) rather than
    crashing startup — a misconfigured external provider should never be
    worse than simply not having one configured.
    """
    try:
        blob = _fetch_secret_blob(provider)
    except Exception:
        log.exception("Failed to fetch secrets from provider '%s'", provider)
        return None
    return blob.get(field_name)


def _fetch_from_vault() -> dict[str, str]:
    try:
        import hvac  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "SECRETS_PROVIDER=vault requires the 'hvac' package: pip install hvac"
        ) from exc
    addr = os.environ.get("VAULT_ADDR")
    token = os.environ.get("VAULT_TOKEN")
    path = os.environ.get("VAULT_SECRET_PATH")
    if not addr or not token or not path:
        raise RuntimeError(
            "SECRETS_PROVIDER=vault requires VAULT_ADDR, VAULT_TOKEN, and VAULT_SECRET_PATH"
        )
    client = hvac.Client(url=addr, token=token)
    resp = client.secrets.kv.v2.read_secret_version(path=path)
    return resp["data"]["data"]


def _fetch_from_aws() -> dict[str, str]:
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "SECRETS_PROVIDER=aws-secrets-manager requires the 'boto3' package: pip install boto3"
        ) from exc
    secret_id = os.environ.get("AWS_SECRETS_MANAGER_SECRET_ID")
    if not secret_id:
        raise RuntimeError("SECRETS_PROVIDER=aws-secrets-manager requires AWS_SECRETS_MANAGER_SECRET_ID")
    client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION"))
    resp = client.get_secret_value(SecretId=secret_id)
    return json.loads(resp["SecretString"])


def _fetch_from_gcp() -> dict[str, str]:
    try:
        from google.cloud import secretmanager  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "SECRETS_PROVIDER=gcp-secret-manager requires the 'google-cloud-secret-manager' "
            "package: pip install google-cloud-secret-manager"
        ) from exc
    project = os.environ.get("GCP_SECRET_PROJECT")
    secret_id = os.environ.get("GCP_SECRET_ID")
    if not project or not secret_id:
        raise RuntimeError("SECRETS_PROVIDER=gcp-secret-manager requires GCP_SECRET_PROJECT and GCP_SECRET_ID")
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    resp = client.access_secret_version(name=name)
    return json.loads(resp.payload.data.decode("utf-8"))


class ExternalSecretsManagerSource(PydanticBaseSettingsSource):
    """pydantic-settings source that injects the three rotatable secrets from
    an external provider. A no-op when SECRETS_PROVIDER is unset/"env".

    Read directly from ``os.environ`` (not the Settings model) because this
    source runs *before* the Settings instance exists — it's one of the
    inputs used to build it.
    """

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if field_name not in EXTERNAL_SECRET_FIELDS:
            return None, field_name, False
        provider = os.environ.get("SECRETS_PROVIDER", "env").strip().lower()
        if provider in ("", "env"):
            return None, field_name, False
        return resolve_secret(provider, field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, field in self.settings_cls.model_fields.items():
            if name not in EXTERNAL_SECRET_FIELDS:
                continue
            value, key, _ = self.get_field_value(field, name)
            if value is not None:
                result[key] = value
        return result
