import logging
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


def problem_response(
    *,
    status: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": type_,
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


def http_exception_handler(request: Request, exc):
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return problem_response(
        status=exc.status_code,
        title="HTTP Error",
        detail=detail,
        type_="https://datatracker.ietf.org/doc/html/rfc7807",
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the full traceback to stdout/stderr so operators can diagnose the root
    # cause without ever exposing it to the caller.
    log.error(
        "Unhandled exception on %s %s\n%s",
        request.method,
        request.url.path,
        traceback.format_exc(),
    )
    return problem_response(
        status=500,
        title="Internal Server Error",
        detail="An internal server error occurred.",
        type_="https://datatracker.ietf.org/doc/html/rfc7807",
    )
