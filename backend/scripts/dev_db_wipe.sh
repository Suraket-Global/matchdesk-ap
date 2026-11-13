#!/usr/bin/env bash
# B13 (was `make demo-reset` until B12): empties the whole local database matchdesk_dev, every
# account included: the Intuit sandbox accounts lose their QuickBooks connections and tokens and must
# be connected again on S-04. Stops the API and worker, drops and recreates the schema (refused when
# MATCHDESK_ENV is production or for another database), starts everything again and loads the demo
# tenant. Files already in local storage stay but are no longer referenced. `make demo-reset` is the
# everyday reset: it rebuilds the demo tenant only.
set -euo pipefail
cd "$(dirname "$0")/.."
if grep -q '^MATCHDESK_ENV=production' .env 2>/dev/null || [ "${MATCHDESK_ENV:-}" = "production" ]; then
  echo "dev-db-wipe: refused, MATCHDESK_ENV is production" >&2; exit 1
fi
export MATCHDESK_MIGRATION_DATABASE_URL="${MATCHDESK_MIGRATION_DATABASE_URL:-postgresql+psycopg://${USER}@localhost:5432/matchdesk_dev}"
case "$MATCHDESK_MIGRATION_DATABASE_URL" in
  */matchdesk_dev) ;;
  *) echo "dev-db-wipe: refused, only the database matchdesk_dev is reset" >&2; exit 1 ;;
esac
scripts/dev_down.sh
.venv/bin/python - <<'PYEOF'
import os
import psycopg
url = os.environ["MATCHDESK_MIGRATION_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
with psycopg.connect(url, autocommit=True) as c:
    c.execute("drop schema if exists public cascade")
    c.execute("create schema public")
    c.execute("grant usage on schema public to public")
print("database: matchdesk_dev emptied")
PYEOF
scripts/dev_up.sh
.venv/bin/python scripts/seed_demo.py
