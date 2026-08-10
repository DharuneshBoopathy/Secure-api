.PHONY: setup up down dev build-frontend test clean reset-env logs migrate lock

# -----------------------------------------------------------------------------
# One-command onboarding:
#     make setup && make up
# -----------------------------------------------------------------------------

# Python launcher: 'py' on Windows, 'python3' elsewhere.
PY ?= $(shell command -v py 2>/dev/null || command -v python3 2>/dev/null || echo python)

# Generate .env with fresh random secrets (no-op if .env already complete).
setup:
	$(PY) scripts/setup_dev_env.py

# Full stack: MySQL + API + nginx + Prometheus + Grafana.
up: setup
	docker compose up --build

# Local dev: dependencies in Docker, API via uvicorn on host.
dev: setup
	docker compose up -d mysql prometheus grafana
	@echo ""
	@echo "Dependencies started. Now run the API locally:"
	@echo "  pip install -r requirements.txt"
	@echo "  make migrate"
	@echo "  uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

# Apply pending Alembic migrations. Schema is owned by alembic/ — the app
# itself no longer runs create_all() at startup (see docs/adr/001).
migrate:
	$(PY) -m alembic upgrade head

# Build the frontend SPA (served by FastAPI when present).
build-frontend:
	cd frontend && npm install && npm run build

# Regenerate requirements.lock after editing requirements.txt.
#
# --universal is not optional. Without it uv resolves for whichever OS you are
# on, and the lock silently excludes the other platform's packages: generated
# on Windows it omits uvloop, and every Linux install then fails with "all
# requirements must be pinned upfront with ==, but found: uvloop" — CI, the
# Docker build and production all at once. With it, one lock carries
# environment markers and installs correctly everywhere.
#
# Keep the version in sync with the pin in .github/workflows/ci.yml, which
# diffs this file's output byte for byte.
lock:
	pipx run --spec uv==0.12.3 uv pip compile requirements.txt \
	  --generate-hashes --universal --python-version 3.12 -o requirements.lock

# Run the backend test suite.
test:
	$(PY) -m pytest

# Stop all containers (volumes preserved).
down:
	docker compose down

# Rotate every secret and re-write .env.
reset-env:
	$(PY) scripts/setup_dev_env.py --force

# Follow container logs.
logs:
	docker compose logs -f --tail=100

# Remove build artefacts + containers + volumes (destructive).
clean: down
	docker volume rm apimonitor_mysql grafana_data apimonitor_loki 2>/dev/null || true
