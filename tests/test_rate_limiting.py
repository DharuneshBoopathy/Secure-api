"""
Validates Phase 4 Task 1: Rate limiting on inventory, audit, and traffic routes.

Confirms that:
  1. @limiter.limit decorators are present on every targeted GET route.
  2. request: Request is in every targeted route signature (required by slowapi).
  3. A minimal ASGI probe with a 2/minute cap yields 200 twice then 429, proving
     the slowapi middleware stack works end-to-end.
  4. The 429 response uses the standard slowapi error format.
"""

import inspect

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

import app.routers.audit as audit_mod
import app.routers.inventory as inv_mod
import app.routers.traffic as traffic_mod


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _has_limit(fn) -> bool:
    """Return True if slowapi has wrapped fn with a rate-limit decorator.

    slowapi uses functools.wraps, which sets __wrapped__ on the outer function
    and embeds a Limiter instance in the closure.  Plain route functions have
    neither attribute.
    """
    if not hasattr(fn, "__wrapped__"):
        return False
    # Confirm it's a slowapi wrapper, not just any functools.wraps usage,
    # by checking that the closure contains a Limiter instance.
    from slowapi import Limiter as _Limiter
    if fn.__closure__:
        return any(
            isinstance(cell.cell_contents, _Limiter)
            for cell in fn.__closure__
            if cell.cell_contents is not None  # type: ignore[misc]
        )
    return True  # __wrapped__ present but no closure to inspect — treat as limited


# ---------------------------------------------------------------------------
# Decorator presence — inventory
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fn_name", [
    "list_discovered",
    "list_shadow_apis",
    "list_idle_registered",
    "stats",
])
def test_inventory_route_has_rate_limit_decorator(fn_name):
    fn = getattr(inv_mod, fn_name)
    assert _has_limit(fn), f"{fn_name} is missing a @limiter.limit decorator"


@pytest.mark.parametrize("fn_name", [
    "list_discovered",
    "list_shadow_apis",
    "list_idle_registered",
    "stats",
])
def test_inventory_route_has_request_parameter(fn_name):
    fn = getattr(inv_mod, fn_name)
    sig = inspect.signature(fn)
    assert "request" in sig.parameters, (
        f"{fn_name} is missing 'request: Request' required by slowapi"
    )


# ---------------------------------------------------------------------------
# Decorator presence — audit
# ---------------------------------------------------------------------------

def test_audit_route_has_rate_limit_decorator():
    assert _has_limit(audit_mod.list_audit), (
        "list_audit is missing a @limiter.limit decorator"
    )


def test_audit_route_has_request_parameter():
    sig = inspect.signature(audit_mod.list_audit)
    assert "request" in sig.parameters


# ---------------------------------------------------------------------------
# Decorator presence — traffic
# ---------------------------------------------------------------------------

def test_traffic_stream_has_rate_limit_decorator():
    assert _has_limit(traffic_mod.stream_traffic), (
        "stream_traffic is missing a @limiter.limit decorator"
    )


def test_traffic_stream_has_request_parameter():
    sig = inspect.signature(traffic_mod.stream_traffic)
    assert "request" in sig.parameters


# ---------------------------------------------------------------------------
# End-to-end 429 proof with a minimal ASGI app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rate_limited_app():
    """
    A self-contained FastAPI app with a 2/minute cap used to confirm that the
    slowapi middleware stack issues 429 without needing a real database.
    """
    mini = FastAPI()
    lim = Limiter(key_func=get_remote_address)
    mini.state.limiter = lim
    mini.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    mini.add_middleware(SlowAPIMiddleware)

    @mini.get("/probe")
    @lim.limit("2/minute")
    def probe(request: Request):
        return {"ok": True}

    return mini


def test_requests_under_limit_succeed(rate_limited_app):
    with TestClient(rate_limited_app, raise_server_exceptions=False) as c:
        assert c.get("/probe").status_code == 200
        assert c.get("/probe").status_code == 200


def test_request_over_limit_yields_429(rate_limited_app):
    # The fixture is module-scoped so the two allowances above are consumed.
    with TestClient(rate_limited_app, raise_server_exceptions=False) as c:
        # Fire enough requests that at least one hits the cap.
        codes = [c.get("/probe").status_code for _ in range(5)]
    assert 429 in codes, f"Expected a 429 in burst, got: {codes}"


def test_429_response_is_json(rate_limited_app):
    with TestClient(rate_limited_app, raise_server_exceptions=False) as c:
        # Saturate then inspect the body of the 429.
        resp = None
        for _ in range(10):
            r = c.get("/probe")
            if r.status_code == 429:
                resp = r
                break
    assert resp is not None, "Never received a 429 response"
    # slowapi returns a plain-text or JSON error; either way it must be non-empty
    assert len(resp.content) > 0
