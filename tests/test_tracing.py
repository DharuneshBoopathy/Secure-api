"""
Phase 6.2 (OpenTelemetry tracing).

Covers:
  1. FastAPIInstrumentor, wired to a TracerProvider with an in-memory
     exporter, actually produces a span for a request end to end — proves
     the instrumentation packages/versions in requirements.txt work
     together in this environment, not just that they import cleanly.
  2. app.tracing.setup_tracing() attaches a span processor (i.e. will
     actually export) only when OTEL_EXPORTER_OTLP_ENDPOINT is set — no
     exporter configured is the common case (dev/CI/no collector deployed
     yet) and shouldn't produce repeated failed-connection log noise.
"""

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.tracing import setup_tracing


def test_fastapi_instrumentation_produces_spans_for_a_request():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    try:
        resp = TestClient(app).get("/ping")
        assert resp.status_code == 200
        spans = exporter.get_finished_spans()
        assert any(s.name == "GET /ping" for s in spans)
    finally:
        FastAPIInstrumentor.uninstrument_app(app)


def test_setup_tracing_has_no_exporter_without_otel_endpoint_env(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    app = FastAPI()
    try:
        provider = setup_tracing(app)
        # No span processors attached => spans are created but immediately
        # dropped, not repeatedly failing to reach a nonexistent collector.
        assert len(provider._active_span_processor._span_processors) == 0
    finally:
        FastAPIInstrumentor.uninstrument_app(app)


def test_setup_tracing_attaches_exporter_when_otel_endpoint_env_set(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    app = FastAPI()
    try:
        provider = setup_tracing(app)
        assert len(provider._active_span_processor._span_processors) == 1
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
