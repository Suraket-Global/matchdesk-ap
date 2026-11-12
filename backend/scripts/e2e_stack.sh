#!/usr/bin/env bash
# B6 (outside QA finding 2): Playwright's own stack. `up` creates the database matchdesk_e2e from
# scratch, migrates it and starts an API on 8102 and a worker against it, with files in a local
# folder of their own; `down` stops both and drops the database. matchdesk_dev is never touched.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
E2E=var/e2e
DB=matchdesk_e2e
export MATCHDESK_ENV=dev
export MATCHDESK_E2E_OWNER_URL="${MATCHDESK_E2E_OWNER_URL:-postgresql+psycopg://${USER}@localhost:5432/postgres}"
export MATCHDESK_DATABASE_URL="postgresql+psycopg://matchdesk_app@localhost:5432/$DB"
export MATCHDESK_MIGRATION_DATABASE_URL="postgresql+psycopg://${USER}@localhost:5432/$DB"
export MATCHDESK_API_PORT="${MATCHDESK_E2E_API_PORT:-8102}"
export MATCHDESK_APP_BASE_URL="${MATCHDESK_E2E_APP_URL:-http://127.0.0.1:5174}"
export MATCHDESK_BLOB_BACKEND=local
export MATCHDESK_BLOB_ROOT="$PWD/$E2E/blobs"

database() { # $1: drop | create
  "$PY" - "$1" "$DB" <<'PYEOF'
import os, sys
import psycopg
action, db = sys.argv[1], sys.argv[2]
url = os.environ["MATCHDESK_E2E_OWNER_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(url, autocommit=True) as c:
    c.execute(f'drop database if exists "{db}" with (force)')
    if action == "create":
        c.execute(f'create database "{db}"')
PYEOF
}

stop() {
  for svc in worker api; do
    f="$E2E/run/$svc.pid"
    if [ -f "$f" ]; then kill "$(cat "$f")" 2>/dev/null || true; rm -f "$f"; fi
  done
}

case "${1:-}" in
  up)
    stop
    rm -rf "$E2E"; mkdir -p "$E2E/run" "$E2E/log" "$E2E/blobs"
    database create
    "$PY" -m alembic upgrade head >"$E2E/log/migrate.log" 2>&1 || { echo "e2e: migrations failed" >&2; exit 1; }
    for svc in api worker; do
      nohup "$PY" -m "matchdesk.$svc" >>"$E2E/log/$svc.log" 2>&1 &
      echo $! >"$E2E/run/$svc.pid"
    done
    deadline=$((SECONDS + 120))
    until curl -fsS "http://127.0.0.1:${MATCHDESK_API_PORT}/readyz" >/dev/null 2>&1; do
      kill -0 "$(cat "$E2E/run/api.pid")" 2>/dev/null || { echo "e2e: api exited (backend/$E2E/log/api.log)" >&2; exit 1; }
      [ $SECONDS -lt $deadline ] || { echo "e2e: api not ready after 120 s" >&2; exit 1; }
      sleep 0.5
    done
    echo "e2e stack: $DB, API http://127.0.0.1:${MATCHDESK_API_PORT}, worker running"
    ;;
  seed) # seed_demo.py with the e2e settings; remaining arguments are passed on
    shift; "$PY" scripts/seed_demo.py "$@" ;;
  down)
    stop; database drop; rm -rf "$E2E"; echo "e2e stack: stopped, $DB dropped" ;;
  *) echo "usage: e2e_stack.sh up|seed ARGS|down" >&2; exit 2 ;;
esac
