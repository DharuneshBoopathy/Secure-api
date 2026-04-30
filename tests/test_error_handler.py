"""
Verifies that generic_exception_handler:
  1. Returns HTTP 500 with the fixed detail string.
  2. Does NOT expose exception text, tracebacks, or internal details in the response.
  3. Logs the full traceback at ERROR level so operators can diagnose issues.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.problem import generic_exception_handler


@pytest.fixture()
def error_app():
    """Minimal FastAPI app wired to the real exception handler."""
    app = FastAPI()
    app.add_exception_handler(Exception, generic_exception_handler)

    @app.get("/boom")
    def boom():
        raise ValueError("secret key logic failed")

    return app


@pytest.fixture()
def client(error_app):
    # raise_server_exceptions=False routes the exception through the handler
    # instead of re-raising it in the test process.
    return TestClient(error_app, raise_server_exceptions=False)


def test_returns_500(client):
    response = client.get("/boom")
    assert response.status_code == 500


def test_detail_is_generic_message(client):
    body = client.get("/boom").json()
    assert body["detail"] == "An internal server error occurred."
    assert body["status"] == 500
    assert body["title"] == "Internal Server Error"


def test_response_does_not_leak_exception_text(client):
    text = client.get("/boom").text
    assert "secret key logic failed" not in text
    assert "ValueError" not in text
    assert "Traceback" not in text
    assert "traceback" not in text


def test_exception_is_logged_at_error_level(client, caplog):
    with caplog.at_level(logging.ERROR, logger="app.problem"):
        client.get("/boom")

    assert any(r.levelno == logging.ERROR for r in caplog.records)
    full_log = "\n".join(r.getMessage() for r in caplog.records)
    assert "secret key logic failed" in full_log
    assert "ValueError" in full_log
