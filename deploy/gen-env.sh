#!/usr/bin/env bash
# B18: write /opt/matchdesk/.env once, with secrets generated on the server by openssl. Refuses to
# overwrite an existing file (the keys seal stored data: a new token key makes sealed secrets
# unreadable, a new backup key makes old backups unreadable). Prints no value.
# Usage (as root on the server): deploy/gen-env.sh <image tag> [app base url]
set -euo pipefail
ENV_FILE=/opt/matchdesk/.env
TAG="${1:?usage: gen-env.sh <image tag> [app base url]}"
BASE_URL="${2:-http://127.0.0.1:8202}"
if [ -e "$ENV_FILE" ]; then
  echo "gen-env: $ENV_FILE exists; not overwritten (edit MATCHDESK_TAG in it instead)" >&2
  exit 1
fi
umask 077
urlsafe() { openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '=\n'; }
{
  echo "# Written by deploy/gen-env.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Secrets: never print or copy."
  echo "MATCHDESK_TAG=$TAG"
  echo "MATCHDESK_APP_BASE_URL=$BASE_URL"
  echo "MATCHDESK_OWNER_DB_PASSWORD=$(openssl rand -hex 32)"
  echo "MATCHDESK_APP_DB_PASSWORD=$(openssl rand -hex 32)"
  echo "MATCHDESK_SESSION_KEY=$(urlsafe 48)"
  echo "MATCHDESK_TOKEN_KEY=$(openssl rand -base64 32 | tr -d '\n')"
  echo "MATCHDESK_TOKEN_KEY_ID=k1"
  echo "MATCHDESK_INBOUND_SIGNING_KEY=$(openssl rand -hex 32)"
  echo "MATCHDESK_BACKUP_KEY=$(urlsafe 48)"
} >"$ENV_FILE"
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "gen-env: wrote $ENV_FILE (mode 600, root); values not shown"
