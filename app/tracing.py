"""OpenTelemetry tracing setup: FastAPI -> SQLAlchemy, end to end per request.

No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set (standard OTel env var —
read directly by OTLPSpanExporter, not duplicated into app.config.Settings).
Unset: spans are still created (instrumentation always runs) but a
TracerProvider with no span processor just drops them — no exporter means
no repeated failed-connection errors in the logs for a deployment that
hasn't set up a collector yet, which is the common case in dev/CI.

See docker-compose.yml's "jaeger" service for a local collector to point
OTEL_EXPORTER_OTLP_ENDPOINT at (http://jaeger:4318), and OTEL_SERVICE_NAME
to set the service name shown in the UI (defaults to "unknown_service" per
the OTel spec if unset).

Known gap: app.worker.py (the Redis-queue consumer) gets its own trace via
setup_worker_tracing() below, but it is NOT the *same* trace as the HTTP
request that enqueued the event — that needs trace-context propagation
through the Redis message itself (inject on enqueue in queue_service.py,
extract on consume in worker.py) which isn't implemented. Deferred rather
than silently skipped: each hop (web request, worker processing) is
individually traceable today, just not yet stitched into one end-to-end
trace across the queue boundary.
"""

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

log = logging.getLogger(__name__)


def _build_tracer_provider(default_service_name: str) -> tuple[TracerProvider, str | None]:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    service_name = os.environ.get("OTEL_SERVICE_NAME", default_service_name)

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        log.info("Tracing enabled: exporting to %s as service %r", endpoint, service_name)
    else:
        log.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing instrumentation is active but spans are not exported")
    return provider, endpoint


def setup_tracing(app) -> TracerProvider:
    provider, _endpoint = _build_tracer_provider("apimonitor-web")
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

    from app.database import engine

    SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)

    return provider


def setup_worker_tracing() -> TracerProvider:
    """Same idea as setup_tracing(), but for app/worker.py: no FastAPI app
    to instrument, just the DB queries process_single_event runs."""
    provider, _endpoint = _build_tracer_provider("apimonitor-worker")
    trace.set_tracer_provider(provider)

    from app.database import engine

    SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)

    return provider
