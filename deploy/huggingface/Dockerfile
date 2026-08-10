# Hugging Face Space wrapper around the released image.
#
# This does not rebuild the application. CD already publishes a multi-arch
# image to GHCR on every green commit, so the Space pulls that and adds only
# the settings the platform needs — builds finish in seconds instead of the
# ten-odd minutes a full frontend+wheels build costs, and what runs here is
# byte-identical to what CI tested.
#
# Pin a specific release instead of :latest by swapping the tag for a commit
# sha; every CD run publishes both.
FROM ghcr.io/dharuneshboopathy/secure-api:latest

# A Space has no database service and no persistent disk, so the app runs the
# SQLite path it already supports (the same one README documents for running
# without Docker). /tmp because the image runs as a non-root user and /app is
# root-owned — and because Space storage is wiped on restart regardless, so
# there is nothing to preserve by writing elsewhere.
#
# Redis and OTLP are deliberately unset. Ingestion then processes inline
# instead of via the worker, and tracing is inert — both are documented
# opt-ins, not requirements (see the architecture section of README.md).
ENV APP_ENV=production \
    DATABASE_URL=sqlite:////tmp/apimonitor.db \
    ENABLE_DEMO=true \
    EXPOSE_API_DOCS=false \
    ALLOW_QUERY_AUTH=false

EXPOSE 8000

# Same command as the base image, plus proxy-header trust: the Space sits
# behind Hugging Face's TLS terminator, so without this every request appears
# to arrive from the proxy and slowapi rate-limits all visitors as one client.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
