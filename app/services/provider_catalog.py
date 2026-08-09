"""Built-in surface definitions for LLM providers onboarded by API key.

The spec-upload path (``/registry/openapi``) works because the operator owns
the API and therefore owns its spec. That falls apart for a third-party API
like Anthropic's or OpenAI's — an operator wiring one up has a key, not a
YAML file. This module is the stand-in: for each known provider it hard-codes
the base URL, the key format, how the key is presented on the wire, a cheap
read-only endpoint to prove the key works, and the endpoint templates to seed
into ``known_endpoints``.

Path templates follow ``app.services.pathutil.path_matches_template`` rules —
a segment is a wildcard only when it is *entirely* ``{...}``. That is why
Gemini's method-style routes are registered as ``/v1beta/models/{model}``
rather than ``/v1beta/models/{model}:generateContent``: the real segment is
``gemini-2.5-pro:generateContent``, and only a whole-segment wildcard matches
it. One template per (method, resource) is the finest granularity the matcher
can actually express there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# How the credential is presented to the upstream provider.
AuthStyle = str  # "bearer" | "x-api-key" | "x-goog-api-key"

CUSTOM_PROVIDER_ID = "custom"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    # Empty pattern = accept any non-blank key (the custom provider).
    key_pattern: re.Pattern[str] | None
    key_hint: str
    auth_style: AuthStyle
    # Sent in addition to the auth header on every probe (Anthropic requires
    # an explicit API version; without it every request 400s).
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Cheap, read-only, side-effect-free GET used to prove a key is live.
    verify_path: str = "/"
    endpoints: tuple[tuple[str, str], ...] = ()

    @property
    def docs_url(self) -> str | None:
        return _DOCS_URLS.get(self.id)


_DOCS_URLS = {
    "anthropic": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
    "google": "https://aistudio.google.com/app/apikey",
}


ANTHROPIC = Provider(
    id="anthropic",
    label="Anthropic (Claude)",
    base_url="https://api.anthropic.com",
    key_pattern=re.compile(r"^sk-ant-[A-Za-z0-9_\-]{16,}$"),
    key_hint="sk-ant-…",
    auth_style="x-api-key",
    extra_headers={"anthropic-version": "2023-06-01"},
    verify_path="/v1/models",
    endpoints=(
        ("POST", "/v1/messages"),
        ("POST", "/v1/messages/count_tokens"),
        ("POST", "/v1/messages/batches"),
        ("GET", "/v1/messages/batches"),
        ("GET", "/v1/messages/batches/{batch_id}"),
        ("POST", "/v1/messages/batches/{batch_id}/cancel"),
        ("GET", "/v1/models"),
        ("GET", "/v1/models/{model_id}"),
        ("GET", "/v1/files"),
        ("POST", "/v1/files"),
        ("GET", "/v1/files/{file_id}"),
        ("DELETE", "/v1/files/{file_id}"),
    ),
)

OPENAI = Provider(
    id="openai",
    label="OpenAI",
    base_url="https://api.openai.com",
    key_pattern=re.compile(r"^sk-[A-Za-z0-9_\-]{16,}$"),
    key_hint="sk-…",
    auth_style="bearer",
    verify_path="/v1/models",
    endpoints=(
        ("POST", "/v1/responses"),
        ("GET", "/v1/responses/{response_id}"),
        ("POST", "/v1/chat/completions"),
        ("POST", "/v1/embeddings"),
        ("POST", "/v1/moderations"),
        ("POST", "/v1/images/generations"),
        ("POST", "/v1/audio/speech"),
        ("POST", "/v1/audio/transcriptions"),
        ("GET", "/v1/models"),
        ("GET", "/v1/models/{model_id}"),
        ("GET", "/v1/files"),
        ("POST", "/v1/files"),
    ),
)

GOOGLE = Provider(
    id="google",
    label="Google Gemini",
    base_url="https://generativelanguage.googleapis.com",
    # AI Studio keys are the literal prefix "AIza" plus 35 more characters.
    key_pattern=re.compile(r"^AIza[A-Za-z0-9_\-]{35}$"),
    key_hint="AIza…",
    # Header auth rather than ?key= — a key in the query string would be
    # written to every proxy access log in the path, exactly what
    # pathutil.redact_sensitive_query_params exists to prevent.
    auth_style="x-goog-api-key",
    verify_path="/v1beta/models",
    endpoints=(
        ("GET", "/v1beta/models"),
        ("GET", "/v1beta/models/{model}"),
        # Covers :generateContent, :streamGenerateContent, :countTokens,
        # :embedContent and :batchEmbedContents — see the module docstring.
        ("POST", "/v1beta/models/{model}"),
        ("GET", "/v1beta/files"),
        ("POST", "/v1beta/files"),
        ("GET", "/v1beta/files/{file_id}"),
        ("DELETE", "/v1beta/files/{file_id}"),
    ),
)

CUSTOM = Provider(
    id=CUSTOM_PROVIDER_ID,
    label="Other / custom API",
    base_url="",
    key_pattern=None,
    key_hint="any key",
    auth_style="bearer",
    verify_path="/",
)

_PROVIDERS: dict[str, Provider] = {p.id: p for p in (ANTHROPIC, OPENAI, GOOGLE, CUSTOM)}


def list_providers() -> list[Provider]:
    return list(_PROVIDERS.values())


def get_provider(provider_id: str) -> Provider | None:
    return _PROVIDERS.get(provider_id)


def validate_key_format(provider: Provider, api_key: str) -> str | None:
    """Return a human-readable reason the key is malformed, or None if it
    looks plausible. A format check only — liveness is the probe's job."""
    key = api_key.strip()
    if not key:
        return "API key is required."
    if any(c.isspace() for c in key):
        return "API key must not contain spaces or line breaks."
    if provider.key_pattern is None:
        return None if len(key) >= 8 else "API key looks too short."
    if not provider.key_pattern.match(key):
        article = "an" if provider.label[0].upper() in "AEIOU" else "a"
        return f"That does not look like {article} {provider.label} key (expected {provider.key_hint})."
    return None


def auth_headers(provider: Provider, api_key: str) -> dict[str, str]:
    key = api_key.strip()
    headers = dict(provider.extra_headers)
    if provider.auth_style == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif provider.auth_style == "x-goog-api-key":
        headers["x-goog-api-key"] = key
    else:
        headers["x-api-key"] = key
    return headers
