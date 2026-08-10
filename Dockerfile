# --- Frontend build ---
FROM node:20-alpine AS frontend-build
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
# --ignore-scripts: no package lifecycle script runs during install, so a
# compromised transitive dependency cannot execute at build time. Verified
# the vite/esbuild build still succeeds without them.
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# --- Python dependencies build ---
FROM python:3.12-slim AS py-build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
# Install from the hash-pinned lockfile, not the floors in requirements.txt,
# so the image contents are determined by the commit rather than by whatever
# happened to be on PyPI at build time. --require-hashes makes a tampered or
# substituted artifact a build failure instead of a silent swap.
COPY requirements.lock .
# --only-binary :all: refuses source distributions, so no setup.py executes
# during install. Every package in the lock publishes a wheel for both
# target architectures, so nothing is lost by requiring one.
RUN pip install --prefix=/install --no-cache-dir --only-binary :all: \
    --require-hashes -r requirements.lock

# --- Runtime ---
FROM python:3.12-slim AS runtime
WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app --uid 1000 app
COPY --from=py-build /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY openapi ./openapi
COPY --from=frontend-build /fe/dist ./frontend/dist

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
USER app
# Schema is owned by Alembic — apply pending migrations before the app
# starts serving traffic. See docs/adr/001-alembic-migration-strategy.md.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
