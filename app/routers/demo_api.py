"""
Sample application routes to exercise discovery through nginx.
Hit these via http://localhost/ (nginx) so access logs feed the monitor.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/v1/health")
def demo_health():
    return {"ok": True}


@router.get("/v1/users/{user_id}")
def demo_user(user_id: int):
    return {"user_id": user_id, "role": "customer"}


@router.post("/internal/debug/echo")
def demo_shadow(body: dict):
    """Undocumented-style internal route (omit from OpenAPI sample)."""
    return {"echo": body}


@router.get("/internal/debug/error", include_in_schema=False)
def demo_error():
    """Validation route: confirms generic_exception_handler sanitises 500 responses.
    Raises intentionally — the response must contain no stack trace or exception text.
    """
    raise ValueError("secret key logic failed")
