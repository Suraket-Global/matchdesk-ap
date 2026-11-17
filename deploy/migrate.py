"""B18 one-shot migration for the Compose stack (deploy/compose.yml, service ``migrate``).

1. ``alembic upgrade head`` as the table owner (MATCHDESK_MIGRATION_DATABASE_URL). Migration 0002
   creates the application role ``matchdesk_app`` (login, no superuser, no bypass of row-level
   security) if it does not exist.
2. Sets that role's password from MATCHDESK_APP_DB_PASSWORD, so the api and worker connect over the
   Compose network as the role subject to row-level security. The password is never printed.

Exits non-zero on any failure; the api and worker start only after this service completed.
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
from psycopg import sql


def main() -> int:
    owner_url = os.environ["MATCHDESK_MIGRATION_DATABASE_URL"]
    app_password = os.environ.get("MATCHDESK_APP_DB_PASSWORD", "")
    if len(app_password) < 24:
        print("migrate: MATCHDESK_APP_DB_PASSWORD missing or too short", file=sys.stderr)
        return 1
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd="/app/backend", check=False
    )
    if done.returncode != 0:
        print("migrate: alembic upgrade failed", file=sys.stderr)
        return done.returncode
    url = owner_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("alter role matchdesk_app with login password {}").format(sql.Literal(app_password))
        )
        head = conn.execute("select version_num from alembic_version").fetchone()
    print(f"migrate: at head {head[0] if head else '?'}; application role password set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
