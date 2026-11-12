"""Row counts of every table in one local database, as JSON (B6: Playwright must leave
matchdesk_dev unchanged). Runs as the database owner so row-level security hides nothing."""

from __future__ import annotations

import json
import os
import sys

import psycopg
from psycopg import sql


def counts(url: str) -> dict[str, int]:
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://")) as c:
        tables = [
            r[0]
            for r in c.execute(
                "select tablename from pg_tables where schemaname = 'public' order by tablename"
            ).fetchall()
        ]
        out: dict[str, int] = {}
        for t in tables:
            stmt = sql.SQL("select count(*) from public.{}").format(sql.Identifier(t))
            row = c.execute(stmt).fetchone()
            out[t] = int(row[0]) if row else 0
        return out


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "matchdesk_dev"
    if not db.startswith("matchdesk_"):
        sys.exit("db_counts: only local matchdesk_* databases")
    user = os.environ.get("USER", "postgres")
    print(json.dumps(counts(f"postgresql://{user}@localhost:5432/{db}"), sort_keys=True))
