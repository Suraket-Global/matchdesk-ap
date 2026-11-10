#!/usr/bin/env bash
# OPS-04: one local start command. Starts api (port 8101) and worker directly (no Docker on this
# machine; the Compose stack of TRD section 7 stays proposed). Exits non-zero naming the failed check.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
RUN=var/run
LOG=var/log
mkdir -p "$RUN" "$LOG" var/blobs
export MATCHDESK_DATABASE_URL="${MATCHDESK_DATABASE_URL:-postgresql+psycopg://matchdesk_app@localhost:5432/matchdesk_dev}"
export MATCHDESK_MIGRATION_DATABASE_URL="${MATCHDESK_MIGRATION_DATABASE_URL:-postgresql+psycopg://${USER}@localhost:5432/matchdesk_dev}"
export MATCHDESK_API_PORT="${MATCHDESK_API_PORT:-8101}"
export MATCHDESK_BLOB_ROOT="${MATCHDESK_BLOB_ROOT:-$PWD/var/blobs}"

fail() { echo "make up: FAILED: $*" >&2; exit 1; }

[ -x "$PY" ] || fail "virtual environment missing: create backend/.venv and pip install -e '.[dev]'"
"$PY" - <<'PYEOF' || fail "database not reachable (is PostgreSQL running? check MATCHDESK_MIGRATION_DATABASE_URL)"
import os, sys
import psycopg
url = os.environ["MATCHDESK_MIGRATION_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
try:
    psycopg.connect(url, connect_timeout=5).close()
except Exception as exc:
    print(f"database check: {type(exc).__name__}", file=sys.stderr)
    sys.exit(1)
PYEOF
echo "database: reachable"
"$PY" -m alembic upgrade head >"$LOG/migrate.log" 2>&1 || fail "migrations (see backend/$LOG/migrate.log)"
echo "migrations: at head"

for svc in api worker; do
  if [ -f "$RUN/$svc.pid" ] && kill -0 "$(cat "$RUN/$svc.pid")" 2>/dev/null; then
    echo "$svc: already running (pid $(cat "$RUN/$svc.pid"))"; continue
  fi
  nohup "$PY" -m "matchdesk.$svc" >>"$LOG/$svc.log" 2>&1 &
  echo $! >"$RUN/$svc.pid"
done

deadline=$((SECONDS + 180))
until curl -fsS "http://127.0.0.1:${MATCHDESK_API_PORT}/readyz" >/dev/null 2>&1; do
  kill -0 "$(cat "$RUN/api.pid")" 2>/dev/null || fail "api exited (see backend/$LOG/api.log)"
  [ $SECONDS -lt $deadline ] || fail "api readiness check timed out after 180 s"
  sleep 1
done
echo "api: ready"
sleep 1
kill -0 "$(cat "$RUN/worker.pid")" 2>/dev/null || fail "worker exited (see backend/$LOG/worker.log)"
echo "worker: running"
echo "MatchDesk up: API http://127.0.0.1:${MATCHDESK_API_PORT} (healthz, readyz, /api/v1)"
