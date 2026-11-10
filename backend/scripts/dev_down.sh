#!/usr/bin/env bash
# Stop the local services started by dev_up.sh; data and volumes are kept.
set -uo pipefail
cd "$(dirname "$0")/.."
for svc in worker api; do
  f="var/run/$svc.pid"
  if [ -f "$f" ]; then
    kill "$(cat "$f")" 2>/dev/null && echo "$svc: stopped" || echo "$svc: not running"
    rm -f "$f"
  fi
done
