#!/usr/bin/env bash
# B18: daily backup of MatchDesk (TRD AD-04: the database and the file volume together).
#   - pg_dump (custom format) of the database "matchdesk" as the table owner
#   - tar of the named volume matchdesk_blobs (the file store)
# Each is encrypted with AES-256-CBC (openssl, PBKDF2) under MATCHDESK_BACKUP_KEY from
# /opt/matchdesk/.env, written to /opt/matchdesk/backups/<UTC date>/, mode 600. The 14 newest daily
# folders are kept. Run by the systemd timer matchdesk-backup (deploy/systemd/); by hand as root:
#   /opt/matchdesk/app/deploy/backup.sh
# Restore: deploy/README.md "Restore".
set -euo pipefail
BASE=/opt/matchdesk
ENV_FILE=$BASE/.env
OUT_ROOT=$BASE/backups
KEEP=14
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$BASE/app/deploy/compose.yml")

BACKUP_KEY="$(sed -n 's/^MATCHDESK_BACKUP_KEY=//p' "$ENV_FILE")"
TAG="$(sed -n 's/^MATCHDESK_TAG=//p' "$ENV_FILE")"
[ -n "$BACKUP_KEY" ] || { echo "backup: MATCHDESK_BACKUP_KEY missing in $ENV_FILE" >&2; exit 1; }
export BACKUP_KEY

umask 077
day="$(date -u +%Y-%m-%d)"
dir="$OUT_ROOT/$day"
tmp="$OUT_ROOT/.partial-$day"
rm -rf "$tmp"
mkdir -p "$tmp"

enc() { openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_KEY -out "$1"; }

# Database: pg_dump inside the db container (no password over the network; local socket).
"${COMPOSE[@]}" exec -T db pg_dump -U matchdesk_owner -d matchdesk -Fc --no-owner | enc "$tmp/db.dump.enc"
# Files: the blob volume read-only through the app image (no extra image pulled).
docker run --rm --network none -v matchdesk_blobs:/data/blobs:ro --entrypoint tar \
  "matchdesk-app:$TAG" -C /data/blobs -cf - . | enc "$tmp/blobs.tar.enc"

# Integrity: both decrypt; the dump's table of contents is readable.
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_KEY -in "$tmp/db.dump.enc" \
  | "${COMPOSE[@]}" exec -T db pg_restore --list >/dev/null
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_KEY -in "$tmp/blobs.tar.enc" | tar -tf - >/dev/null
(cd "$tmp" && sha256sum db.dump.enc blobs.tar.enc >SHA256SUMS)
echo "tag=$TAG" >"$tmp/INFO"

rm -rf "$dir"
mv "$tmp" "$dir"
# Keep the newest $KEEP daily folders.
find "$OUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' | sort -r | tail -n +$((KEEP + 1)) | xargs -r rm -rf
echo "backup: $dir ($(du -sh "$dir" | cut -f1)); $(find "$OUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??' | wc -l) kept"
