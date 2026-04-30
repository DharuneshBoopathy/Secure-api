#!/usr/bin/env bash
# ============================================================
#  setup-dev-env.sh
#  Thin POSIX wrapper around scripts/setup_dev_env.py.  Bootstraps a
#  development .env file with cryptographically random secrets.
#
#  Usage:
#     ./scripts/setup-dev-env.sh           # generate only if missing
#     ./scripts/setup-dev-env.sh --force   # rotate every secret
# ============================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-python}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON=python3
    else
        echo "ERROR: python is required to bootstrap the dev environment." >&2
        exit 1
    fi
fi

exec "$PYTHON" "$HERE/setup_dev_env.py" "$@"
