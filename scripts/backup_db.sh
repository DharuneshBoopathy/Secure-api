#!/usr/bin/env bash
# Database backup and restore.
#
# The database is the only source of truth for the endpoint inventory, alert
# history and the audit log — none of it is reconstructable from traffic once
# it is gone. Retention of the backups themselves is your call; see
# docs/data-retention-policy.md for what the application prunes on its own.
#
#   ./scripts/backup_db.sh backup                  # write a timestamped dump
#   ./scripts/backup_db.sh restore <file>          # restore from one
#   ./scripts/backup_db.sh verify <file>           # check a dump is loadable
#
# Reads DATABASE_URL from the environment or .env. MySQL and SQLite are both
# supported, because the project runs on MySQL in Docker and SQLite locally.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ -z "${DATABASE_URL:-}" && -f .env ]]; then
  DATABASE_URL="$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)"
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set and no .env was found" >&2
  exit 1
fi

die() { echo "error: $*" >&2; exit 1; }

# --- dialect ---------------------------------------------------------------
case "$DATABASE_URL" in
  sqlite*) DIALECT=sqlite ;;
  mysql*)  DIALECT=mysql ;;
  *)       die "unsupported DATABASE_URL dialect: ${DATABASE_URL%%:*}" ;;
esac

sqlite_path() { echo "${DATABASE_URL#sqlite:///}"; }

# mysql+pymysql://user:pass@host:port/dbname -> exported as MYSQL_* for the client
parse_mysql() {
  local rest="${DATABASE_URL#*://}"
  local creds="${rest%%@*}"
  local hostpart="${rest#*@}"
  MYSQL_USER="${creds%%:*}"
  MYSQL_PWD="${creds#*:}"
  MYSQL_DB="${hostpart#*/}"
  MYSQL_DB="${MYSQL_DB%%\?*}"
  local hostport="${hostpart%%/*}"
  MYSQL_HOST="${hostport%%:*}"
  MYSQL_PORT="${hostport#*:}"
  [[ "$MYSQL_PORT" == "$MYSQL_HOST" ]] && MYSQL_PORT=3306
  export MYSQL_PWD
}

# --- commands --------------------------------------------------------------
cmd_backup() {
  mkdir -p "$BACKUP_DIR"
  if [[ "$DIALECT" == sqlite ]]; then
    local src out; src="$(sqlite_path)"; out="$BACKUP_DIR/apimonitor-$STAMP.sqlite"
    # Python's sqlite3 rather than the sqlite3 CLI, which isn't installed on
    # every host that can run this app. Connection.backup() takes the same
    # consistent snapshot with the app running; copying the file directly can
    # capture a half-written page.
    "${PYTHON:-python}" - "$src" "$out" <<'PYEOF'
import sqlite3, sys
src, dest = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
    s.backup(d)
PYEOF
    gzip -f "$out"
    echo "$out.gz"
  else
    parse_mysql
    local out="$BACKUP_DIR/apimonitor-$STAMP.sql.gz"
    # single-transaction keeps InnoDB consistent without locking writers out.
    mysqldump --host="$MYSQL_HOST" --port="$MYSQL_PORT" --user="$MYSQL_USER" \
      --single-transaction --quick --routines --triggers \
      "$MYSQL_DB" | gzip > "$out"
    echo "$out"
  fi
}

cmd_restore() {
  local file="${1:?usage: restore <file>}"
  [[ -f "$file" ]] || die "no such file: $file"
  echo "This OVERWRITES the database at $DATABASE_URL." >&2
  read -r -p "Type the database name to confirm: " confirm
  if [[ "$DIALECT" == sqlite ]]; then
    local dest; dest="$(sqlite_path)"
    [[ "$confirm" == "$(basename "$dest")" ]] || die "confirmation did not match"
    gunzip -c "$file" > "$dest.restore.tmp"
    mv "$dest.restore.tmp" "$dest"
  else
    parse_mysql
    [[ "$confirm" == "$MYSQL_DB" ]] || die "confirmation did not match"
    gunzip -c "$file" | mysql --host="$MYSQL_HOST" --port="$MYSQL_PORT" \
      --user="$MYSQL_USER" "$MYSQL_DB"
  fi
  echo "restored. Run 'alembic upgrade head' if the dump predates the current schema."
}

# A backup nobody has restored is a hypothesis, not a backup. This loads the
# dump into a scratch database and counts rows, without touching the live one.
cmd_verify() {
  local file="${1:?usage: verify <file>}"
  [[ -f "$file" ]] || die "no such file: $file"
  local tmp; tmp="$(mktemp -d)"
  # Expand now, not at exit: `tmp` is function-local and already out of scope
  # by the time the EXIT trap runs, which under `set -u` aborts the cleanup.
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT
  if [[ "$DIALECT" == sqlite ]]; then
    gunzip -c "$file" > "$tmp/check.sqlite"
    "${PYTHON:-python}" - "$tmp/check.sqlite" <<'PYEOF'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
    sys.exit("integrity check failed")
tables = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
users = c.execute("SELECT count(*) FROM users").fetchone()[0]
print(f"  tables: {tables}")
print(f"  users:  {users}")
PYEOF
  else
    parse_mysql
    local scratch="verify_${STAMP//[^0-9]/}"
    mysql --host="$MYSQL_HOST" --port="$MYSQL_PORT" --user="$MYSQL_USER" \
      -e "CREATE DATABASE \`$scratch\`;"
    # shellcheck disable=SC2064
    trap "mysql --host='$MYSQL_HOST' --port='$MYSQL_PORT' --user='$MYSQL_USER' -e 'DROP DATABASE \`$scratch\`;'; rm -rf '$tmp'" EXIT
    gunzip -c "$file" | mysql --host="$MYSQL_HOST" --port="$MYSQL_PORT" --user="$MYSQL_USER" "$scratch"
    mysql --host="$MYSQL_HOST" --port="$MYSQL_PORT" --user="$MYSQL_USER" "$scratch" \
      -e "SELECT COUNT(*) AS users FROM users;"
  fi
  echo "verified: $file"
}

case "${1:-}" in
  backup)  cmd_backup ;;
  restore) shift; cmd_restore "$@" ;;
  verify)  shift; cmd_verify "$@" ;;
  *) sed -n '2,14p' "$0"; exit 1 ;;
esac
