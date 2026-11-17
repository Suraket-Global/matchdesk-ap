# Deploying MatchDesk (B18, 2026-11-18)

MatchDesk runs on the owner's server as one Docker Compose project, `matchdesk`. B18 deploys it
without a domain: everything listens on `127.0.0.1` and is reached through an SSH tunnel. B19 adds the
domain, TLS and the opening of ports 80 and 443.

The server also runs other people's production applications. Nothing in this file stops,
restarts, reconfigures or upgrades them, and nothing here changes sshd or ufw. Every MatchDesk
port is published on `127.0.0.1` only (Docker's published ports bypass ufw); `/etc/docker/daemon.json`
also sets `"ip": "127.0.0.1"` as the default for published ports.

## What runs

| Service | Image | Published | Purpose |
|---|---|---|---|
| `db` | `postgres:16-bookworm` | none | Database `matchdesk`; volume `matchdesk_pgdata` |
| `migrate` | `matchdesk-app:<tag>` | none | One-shot: `alembic upgrade head` as the table owner, then sets the password of the application role `matchdesk_app` (row-level security applies to it). `api` and `worker` start only after it succeeded |
| `api` | `matchdesk-app:<tag>` | `127.0.0.1:8201` | API (`/healthz`, `/readyz`, `/api/v1`); files on volume `matchdesk_blobs` |
| `worker` | `matchdesk-app:<tag>` | none | Jobs and the once-a-minute schedule; 1 GB memory limit (TRD 8.7) |
| `web` | `matchdesk-web:<tag>` | `127.0.0.1:8202` app, `127.0.0.1:8203` landing | nginx: the built web app, `/api` and `/oauth` proxied to `api`, TRD 8.7 response headers; the landing page on its own port |
| `mailpit` | `axllent/mailpit` | `127.0.0.1:8225` (inbox UI) | Temporary mail catcher until the owner's SMTP account is set |
| `demo-seed`, `operator-code` | `matchdesk-app:<tag>` | none | Profile `demo`, run by hand only (below) |

Settings: `MATCHDESK_ENV=production`, Secure `__Host-` cookies (`MATCHDESK_LOCAL_HTTP_COOKIES` is not
set), `MATCHDESK_QBO_MODE=recorded`, `MATCHDESK_EXTRACTOR=local`, `MATCHDESK_BLOB_BACKEND=local`.
`MATCHDESK_APP_BASE_URL` is `http://127.0.0.1:8202`, the tunnel address, until B19.

Layout on the server:

```
/opt/matchdesk/            mode 700, root
  .env                     secrets, mode 600, root (deploy/gen-env.sh); never printed or copied off
  app/                     the repository at the deployed commit (no .env, var/, .venv, node_modules)
  backups/<YYYY-MM-DD>/    db.dump.enc, blobs.tar.enc, SHA256SUMS, INFO (14 kept)
  check.sh                 state of the server's other services, ports and ufw (read-only)
```

All commands below run as root on the server and use this shorthand:

```sh
dc() { docker compose --env-file /opt/matchdesk/.env -f /opt/matchdesk/app/deploy/compose.yml "$@"; }
```

## First deploy

1. Docker Engine and the Compose plugin from Docker's apt repository
   (docs.docker.com/engine/install/ubuntu), after checking that nothing used Docker or 172.17.0.0/16.
   The Compose network is `172.30.18.0/24`.
2. Copy the repository at the commit to `/opt/matchdesk/app` (rsync of `git ls-files`, or
   `git clone` + `git checkout <commit>`); never `backend/.env`, `backend/var/` or `.venv`.
3. `/opt/matchdesk/app/deploy/gen-env.sh <short commit>`: writes `/opt/matchdesk/.env` with every
   secret from `openssl rand`. It refuses to overwrite an existing file. Store a copy of
   `MATCHDESK_BACKUP_KEY` off the server (password manager) by reading it on the server yourself.
4. `dc build && dc up -d`, then `dc ps`: `api`, `worker`, `web`, `mailpit`, `db` healthy, `migrate`
   exited 0.
5. Backup timer: `install -m 644 /opt/matchdesk/app/deploy/systemd/matchdesk-backup.* /etc/systemd/system/`,
   `systemctl daemon-reload && systemctl enable --now matchdesk-backup.timer`.

## Opening it through the SSH tunnel (until B19)

From the Mac:

```sh
ssh -i ~/.ssh/matchdesk_deploy -N \
  -L 8202:127.0.0.1:8202 -L 8203:127.0.0.1:8203 -L 8225:127.0.0.1:8225 root@185.174.253.63
```

- App: http://127.0.0.1:8202 (use this exact origin; it is `MATCHDESK_APP_BASE_URL`, and the API
  refuses another `Origin`). The session cookies are `Secure` with the `__Host-` prefix; Chromium
  browsers accept them on `http://127.0.0.1` because a loopback address counts as a secure context.
- Landing page: http://127.0.0.1:8203
- Mailpit (sign-in links): http://127.0.0.1:8225

## Demo account

The server holds only the synthetic demo account (docs/PLAY.md), never real customer data.

```sh
dc --profile demo run --rm demo-seed > /opt/matchdesk/demo-seed.txt 2>&1; chmod 600 /opt/matchdesk/demo-seed.txt
dc --profile demo run --rm operator-code     # current code of operator.demo@example.invalid
```

The seed is the same as `make seed-demo ARGS=--preload` on a fresh database: the tenant "Demo
Distributor Ltd (synthetic)", `controller.demo@example.invalid`, `clerk.demo@example.invalid`,
`operator.demo@example.invalid` (TOTP), the receiving log and the 13 invoices uploaded and processed.
`seed_demo.py` and `operator_code.py` refuse `MATCHDESK_ENV=production`; these two one-shot
services run with `MATCHDESK_ENV=demo` while the api and worker stay in production. The seed's
output contains the operator's TOTP secret and stays in the root-only file above. **Before the first
real account (B19 or later), remove the demo account**: with no other account on the database,
`dc down`, `docker volume rm matchdesk_pgdata matchdesk_blobs`, `dc up -d`; and stop using the
`demo` profile.

## Update

```sh
# on the Mac: the commit to deploy is on the branch; copy it
git ls-files -co --exclude-standard > /tmp/files.txt
rsync -a --delete --files-from=/tmp/files.txt -e "ssh -i ~/.ssh/matchdesk_deploy" ./ root@185.174.253.63:/opt/matchdesk/app/
# on the server
/opt/matchdesk/app/deploy/backup.sh                          # backup before every update
sed -i 's/^MATCHDESK_TAG=.*/MATCHDESK_TAG=<new short commit>/' /opt/matchdesk/.env
dc build && dc up -d                                         # migrate runs first, then api/worker
dc ps
```

Migrations only expand (AGENTS.md section 7), so the previous image runs on the migrated database.

## Roll back

Images stay tagged by commit (`docker image ls matchdesk-app`). Set `MATCHDESK_TAG` in `.env` to the
previous tag and run `dc up -d`. The source in `/opt/matchdesk/app` only matters for building; copy
the old commit back before the next build. If a release must be undone together with its data, restore
the backup taken before the update (below).

## Back up

`deploy/backup.sh`, run daily at 03:30 UTC by the systemd timer `matchdesk-backup` (units in
`deploy/systemd/`): `pg_dump -Fc` of `matchdesk` and a tar of the volume `matchdesk_blobs`, each
encrypted with AES-256-CBC (openssl, PBKDF2, 200,000 iterations) under `MATCHDESK_BACKUP_KEY`,
checked by decrypting (the dump's table of contents and the tar listing), written to
`/opt/matchdesk/backups/<UTC date>/` mode 600; the 14 newest daily folders are kept. Logs:
`journalctl -u matchdesk-backup`. The backups are on the same server: copying them elsewhere is
still open (B19 or later).

## Restore

```sh
d=/opt/matchdesk/backups/<YYYY-MM-DD>
export BACKUP_KEY="$(sed -n 's/^MATCHDESK_BACKUP_KEY=//p' /opt/matchdesk/.env)"
dec() { openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_KEY -in "$1"; }
(cd "$d" && sha256sum -c SHA256SUMS)
dc stop api worker web
# database: into the existing (or freshly created) database, as the table owner
dec "$d/db.dump.enc" | dc exec -T db pg_restore -U matchdesk_owner -d matchdesk --clean --if-exists --no-owner
# files
docker run --rm -v matchdesk_blobs:/data/blobs --entrypoint sh matchdesk-app:<tag> -c 'find /data/blobs -mindepth 1 -delete'
dec "$d/blobs.tar.enc" | docker run --rm -i -u 10001 -v matchdesk_blobs:/data/blobs --entrypoint tar matchdesk-app:<tag> -C /data/blobs -xf -
dc up -d   # migrate re-applies the application role's password, then api and worker start
```

After a restore onto a new server, `.env` must carry the same `MATCHDESK_TOKEN_KEY` (it seals the
TOTP seeds and QuickBooks tokens) and `MATCHDESK_BACKUP_KEY`.

## Live on bitloomix.io (2026-11-18)

The server's existing Cloudflare tunnel (`/etc/cloudflared/config.yml`, shared with other apps)
carries MatchDesk; no port is opened and ufw is unchanged. Two Cloudflare DNS records (proxied CNAME
to the tunnel) and two ingress lines, added before the final 404 rule:

- `matchdesk.bitloomix.io` → `http://127.0.0.1:8203` (landing page)
- `matchdesk-app.bitloomix.io` → `http://127.0.0.1:8202` (the app)

`MATCHDESK_APP_BASE_URL=https://matchdesk-app.bitloomix.io` in `.env`. A change to the tunnel config
needs `systemctl restart cloudflared`, which briefly interrupts the other apps on the tunnel: back up
the file first and check every hostname after. Still open: the owner's SMTP (Mailpit holds sign-in
mail until then), client addresses behind the tunnel (`CF-Connecting-IP` is not yet passed on, so
rate limits see the tunnel's address), removing the demo account before the first real customer.

## What B19 adds with the domain

- DNS: `yourdomain.com` and `app.yourdomain.com` to the server.
- A TLS proxy on 80/443 (for example Caddy as one more Compose service, certificates from Let's
  Encrypt), and ufw opened for 80/443 only then:
  - `yourdomain.com` → `web:8081` (the landing page)
  - `app.yourdomain.com` → `web:8080` (the app; `/api` and `/oauth` are proxied on by nginx)
- `MATCHDESK_APP_BASE_URL=https://app.yourdomain.com` in `.env`, then `dc up -d`; the SSH tunnel
  address stops working for sign-in.
- `MATCHDESK_TRUSTED_PROXIES`: nginx in `web` sets `X-Forwarded-For` to its own peer, so with a
  proxy in front, nginx must pass the real client address on (`real_ip` from the proxy's address)
  and the trusted list stays the `web` container.
- The owner's SMTP account in `.env` (`MATCHDESK_SMTP_*`, `MATCHDESK_MAIL_FROM` on the domain with SPF
  and DKIM), and the `mailpit` service removed.
- The demo account removed before the first real account (above); backups copied off the server.
