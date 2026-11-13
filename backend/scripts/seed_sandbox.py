"""B11: a second synthetic tenant whose controller connects the Intuit sandbox on S-04.

Creates "Sandbox Distributor (Intuit sandbox)" with ``tenants.qbo_mode = 'intuit'`` and currency USD
(Intuit's sample sandbox company is a US company in USD; documents in another currency than the
account's are skipped, B11-1), a controller
and a clerk with ``.invalid`` addresses, and no QuickBooks connection: the controller signs in and
presses "Connect to QuickBooks", which runs Intuit's real authorization-code flow with the app
credentials in ``backend/.env``. The demo tenant and its recorded responses are untouched.

Refuses in production, and when ``MATCHDESK_QBO_CLIENT_ID``, ``MATCHDESK_QBO_CLIENT_SECRET`` or
``MATCHDESK_QBO_REDIRECT_URI`` is empty (it names the setting, never prints a value). Warns when the
redirect URI is not on ``MATCHDESK_APP_BASE_URL``'s origin: the session cookie belongs to one host,
so the stack must run with the app on the redirect URI's origin (``make sandbox-up``). Idempotent.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select

from matchdesk.core import load_settings
from matchdesk.identity import Membership, Tenant, User
from matchdesk.tenancy import get_engine, global_session, session

ROOT = Path(__file__).resolve().parents[1]
TENANT = "Sandbox Distributor (Intuit sandbox)"
CONTROLLER = "controller.sandbox@example.invalid"
CLERK = "clerk.sandbox@example.invalid"
CURRENCY = "USD"  # the sandbox sample company's currency (T-1.1.1, 2026-11-13)


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def main() -> int:
    settings = load_settings()
    if settings.env.lower() in {"production", "prod"}:
        print("seed-sandbox: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    missing = [
        name
        for name, value in (
            ("MATCHDESK_QBO_CLIENT_ID", settings.qbo_client_id),
            ("MATCHDESK_QBO_CLIENT_SECRET", settings.qbo_client_secret),
            ("MATCHDESK_QBO_REDIRECT_URI", settings.qbo_redirect_uri),
        )
        if not value
    ]
    if missing:
        print("seed-sandbox: refused, not set in backend/.env: " + ", ".join(missing), file=sys.stderr)
        return 1
    env = {**os.environ, "MATCHDESK_MIGRATION_DATABASE_URL": settings.migration_database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = get_engine(settings.database_url)
    with global_session(engine) as s:
        found = s.scalar(select(Tenant).where(Tenant.name == TENANT))
        if found is not None:
            if found.currency != CURRENCY or found.qbo_mode != "intuit":
                found.currency, found.qbo_mode = CURRENCY, "intuit"
                print(f"seed-sandbox: '{TENANT}' set to currency {CURRENCY}, QuickBooks mode intuit")
            else:
                print(f"seed-sandbox: '{TENANT}' already exists; nothing changed")
            tid = None
        else:
            t = Tenant(name=TENANT, qbo_mode="intuit", currency=CURRENCY)
            s.add(t)
            users = []
            for email, name in ((CONTROLLER, "Sandbox Controller"), (CLERK, "Sandbox Clerk")):
                u = s.scalar(select(User).where(User.email == email)) or User(email=email, display_name=name)
                s.add(u)
                users.append(u)
            s.flush()
            tid, ctrl_id, clerk_id = t.id, users[0].id, users[1].id
    if tid is not None:
        with session(tid, engine) as s:
            s.add_all(
                [
                    Membership(tenant_id=tid, user_id=ctrl_id, role="controller"),
                    Membership(tenant_id=tid, user_id=clerk_id, role="clerk"),
                ]
            )
        print(
            f"seed-sandbox: created '{TENANT}' (QuickBooks mode: intuit, currency {CURRENCY}, not connected)"
        )
    print(f"  controller: {CONTROLLER}   clerk: {CLERK}")
    redirect, app = _origin(settings.qbo_redirect_uri), _origin(settings.app_base_url)
    print(f"  sign in at {redirect}/login, then Settings > QuickBooks > Connect to QuickBooks")
    if redirect != app:
        print(
            f"  note: MATCHDESK_APP_BASE_URL is {app}, the redirect URI is on {redirect}; "
            "start the stack with make sandbox-up so both are the same host"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
