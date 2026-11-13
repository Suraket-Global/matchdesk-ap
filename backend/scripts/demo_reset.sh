#!/usr/bin/env bash
# B4, changed in B13: a clean demo. Stops the API and worker, removes the demo tenant "Demo
# Distributor Ltd (synthetic)" and every row it owns from matchdesk_dev (scripts/demo_tenant_reset.py),
# starts everything again and seeds the demo tenant. Every other account, such as the Intuit sandbox
# accounts with their QuickBooks connections and tokens, is kept. Refused in production and on any
# other database. `make dev-db-wipe` still empties the whole database when that is really wanted.
set -euo pipefail
cd "$(dirname "$0")/.."
if grep -q '^MATCHDESK_ENV=production' .env 2>/dev/null || [ "${MATCHDESK_ENV:-}" = "production" ]; then
  echo "demo-reset: refused, MATCHDESK_ENV is production" >&2; exit 1
fi
export MATCHDESK_MIGRATION_DATABASE_URL="${MATCHDESK_MIGRATION_DATABASE_URL:-postgresql+psycopg://${USER}@localhost:5432/matchdesk_dev}"
case "$MATCHDESK_MIGRATION_DATABASE_URL" in
  */matchdesk_dev) ;;
  *) echo "demo-reset: refused, only the database matchdesk_dev is reset" >&2; exit 1 ;;
esac
scripts/dev_down.sh
.venv/bin/python scripts/demo_tenant_reset.py
scripts/dev_up.sh
.venv/bin/python scripts/seed_demo.py
