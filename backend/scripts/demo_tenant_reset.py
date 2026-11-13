"""B13: remove the demo tenant, and only it, so ``make demo-reset`` can seed it again.

``make demo-reset`` used to empty the whole database ``matchdesk_dev``, which also removed the sandbox
accounts and their QuickBooks connections and tokens (the B6 rule: a seed script touches only its own
tenant). This script deletes every row of one tenant, found by its exact name (default: the demo
tenant "Demo Distributor Ltd (synthetic)"), in dependency order, in one transaction, then the tenant
row. Users stay (they are global and may belong to other accounts); the demo's stored files are left
in local storage, unreferenced, as before.

It refuses in production, on any database other than ``matchdesk_dev`` or ``matchdesk_test``, and
for a tenant in Intuit mode (a sandbox account is never a demo).
It runs as the owner role (``MATCHDESK_MIGRATION_DATABASE_URL``) with the transaction setting
``app.purge``, the same rule that lets ``purge_tenant()`` remove insert-only rows (schema.md 8);
no ``deletion_ledger`` row is written, because nothing a customer owns is deleted. Prints counts
only.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

DEMO = "Demo Distributor Ltd (synthetic)"
ALLOWED_DATABASES = ("matchdesk_dev", "matchdesk_test")


def reset_tenant(url: str, name: str) -> int | None:
    """Delete one tenant and every row it owns. Returns the rows deleted, or None if absent."""
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            found = c.execute(
                text("select id, qbo_mode from tenants where name = :n for update"), {"n": name}
            ).one_or_none()
            if found is None:
                return None
            tid, mode = found
            if mode == "intuit":
                raise SystemExit(f"demo-reset: refused, '{name}' is an Intuit account")
            c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tid)})
            c.execute(text("select set_config('app.purge', 'on', true)"))
            c.execute(text("delete from sessions where active_tenant_id = :t"), {"t": tid})
            c.execute(text("delete from job_queue where payload->>'tenant_id' = :t"), {"t": str(tid)})
            remaining = [
                r[0]
                for r in c.execute(
                    text(
                        "select c.table_name from information_schema.columns c "
                        "join information_schema.tables tb on tb.table_schema = c.table_schema "
                        "and tb.table_name = c.table_name "
                        "where c.table_schema = 'public' and c.column_name = 'tenant_id' "
                        "and tb.table_type = 'BASE TABLE' and c.table_name <> 'deletion_ledger' "
                        "order by c.table_name"
                    )
                ).all()
            ]
            total = 0
            while remaining:
                progressed = False
                for table in list(remaining):
                    try:
                        with c.begin_nested():
                            res = c.execute(text(f'delete from "{table}" where tenant_id = :t'), {"t": tid})  # noqa: S608
                    except Exception as exc:  # a row still refers to this table; try after the others
                        if "foreign key" not in str(exc).lower():
                            raise
                        continue
                    total += int(res.rowcount or 0)
                    remaining.remove(table)
                    progressed = True
                if not progressed:
                    raise SystemExit("demo-reset: blocked by " + ", ".join(remaining))
            c.execute(text("delete from tenants where id = :t"), {"t": tid})
            return total
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo-tenant-reset", description=__doc__.splitlines()[0])
    ap.add_argument("--name", default=DEMO, help="exact tenant name (default: the demo tenant)")
    args = ap.parse_args(argv)
    if os.environ.get("MATCHDESK_ENV", "").lower() in {"production", "prod"}:
        print("demo-reset: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    url = os.environ.get("MATCHDESK_MIGRATION_DATABASE_URL", "")
    database = urlsplit(url.replace("postgresql+psycopg", "postgresql")).path.lstrip("/")
    if database not in ALLOWED_DATABASES:
        print(f"demo-reset: refused, only {' or '.join(ALLOWED_DATABASES)} is reset", file=sys.stderr)
        return 1
    if not args.name.startswith(DEMO):
        print(f"demo-reset: refused, only a tenant named '{DEMO}…' is reset", file=sys.stderr)
        return 1
    n = reset_tenant(url, args.name)
    if n is None:
        print(f"demo-reset: no tenant '{args.name}'; nothing removed")
    else:
        print(f"demo-reset: removed '{args.name}' ({n} rows); other accounts untouched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
