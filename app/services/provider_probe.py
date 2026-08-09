"""Outbound liveness check for a key-onboarded API.

This is the only place the app makes an outbound request on behalf of a user,
and the target URL is operator-supplied for the custom provider — i.e. a
textbook SSRF sink. ``assert_safe_target`` is the gate: HTTPS only, and every
address the hostname resolves to must be globally routable, so a saved
connection can't be used to probe cloud metadata endpoints (169.254.169.254),
loopback, or anything else on the internal network.

The check resolves DNS itself and then hands the *hostname* to httpx, which
resolves again — a rebinding window exists in principle. Closing it fully
means pinning the connection to the vetted IP, which breaks TLS SNI/virtual
hosting for the three real providers this feature exists to serve. The
residual risk is bounded: the response body is never returned to the caller,
only a status classification.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from app.services.provider_catalog import Provider, auth_headers

PROBE_TIMEOUT_SECONDS = 10.0

# Classification of a probe outcome, stored on MonitoredApi.status.
STATUS_ACTIVE = "active"
STATUS_INVALID = "invalid"
STATUS_ERROR = "error"
STATUS_UNVERIFIED = "unverified"


class UnsafeTargetError(ValueError):
    """The target URL is not a safe destination for a server-side request."""


def assert_safe_target(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeTargetError("Base URL must use https:// — credentials are never sent over plaintext HTTP.")
    host = parsed.hostname
    if not host:
        raise UnsafeTargetError("Base URL has no host.")
    try:
        resolved = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeTargetError(f"Could not resolve host {host!r}.") from e
    for info in resolved:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise UnsafeTargetError(
                f"{host} resolves to the non-public address {addr} — refusing to send credentials there."
            )


def probe(provider: Provider, api_key: str, base_url: str, verify_path: str | None = None) -> tuple[str, str]:
    """Send one authenticated GET upstream and classify the result.

    Returns ``(status, detail)`` where status is one of STATUS_ACTIVE /
    STATUS_INVALID / STATUS_ERROR. Never raises for an upstream failure — a
    dead provider is a connection state to display, not a 500.
    """
    path = verify_path if verify_path is not None else provider.verify_path
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    try:
        assert_safe_target(url)
    except UnsafeTargetError as e:
        return STATUS_ERROR, str(e)

    try:
        with httpx.Client(timeout=PROBE_TIMEOUT_SECONDS, follow_redirects=False) as client:
            # follow_redirects=False: a redirect would replay the credential
            # header at whatever host the response names, bypassing the check
            # above.
            resp = client.get(url, headers=auth_headers(provider, api_key))
    except httpx.TimeoutException:
        return STATUS_ERROR, f"Timed out after {PROBE_TIMEOUT_SECONDS:.0f}s contacting {urlparse(url).netloc}."
    except httpx.HTTPError as e:
        return STATUS_ERROR, f"Could not reach {urlparse(url).netloc}: {type(e).__name__}."

    code = resp.status_code
    if 200 <= code < 300:
        return STATUS_ACTIVE, f"HTTP {code} from GET {path} — key accepted."
    if code in (401, 403):
        return STATUS_INVALID, f"HTTP {code} from GET {path} — the provider rejected this key."
    if code == 429:
        # Throttling is applied after authentication, so the key is good.
        return STATUS_ACTIVE, f"HTTP 429 from GET {path} — key accepted but rate-limited upstream."
    if code == 404:
        return STATUS_ERROR, f"HTTP 404 — no endpoint at GET {path}. Check the base URL."
    return STATUS_ERROR, f"HTTP {code} from GET {path}."
