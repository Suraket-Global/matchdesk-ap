"""``make demo-po-change`` (B9, S-10): read QuickBooks again from recorded responses taken after a
change in QuickBooks, for the local demo company.

The responses in ``fixtures/qbo/recorded-changed/`` are the demo's own recorded responses with two
invented edits: purchase order 4471 line 1 ordered 80 instead of 100, and purchase order 4390 line 2
deleted, plus a vendor credit VC-DEMO-9 of 168.00 with no invoice number and no lines, which ties only
by supplier and amount and so flags FF-1003 "possibly credited" for the controller to decide (S-09).
The read runs the real sync (``request_sync``, ``execute_sync``) in recorded-response mode,
so S-10 shows "Changed in QuickBooks" with the old and new values and the worker re-matches the
affected lines. Nothing is written to QuickBooks. Refuses in production.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

from matchdesk.core import load_settings
from matchdesk.identity import Membership, Tenant
from matchdesk.qbo import RecordedQboReader, execute_sync, request_sync
from matchdesk.schema_registry import load_all_models
from matchdesk.tenancy import get_engine, global_session, session

TENANT = os.environ.get("MATCHDESK_DEMO_TENANT", "Demo Distributor Ltd (synthetic)")
CHANGED = Path(__file__).resolve().parents[1] / "fixtures" / "qbo" / "recorded-changed"


def main() -> int:
    settings = load_settings()
    if settings.env == "production":
        print("demo-po-change: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    load_all_models()
    engine = get_engine(settings.database_url)
    with global_session(engine) as g:
        tid = g.scalar(select(Tenant.id).where(Tenant.name == TENANT))
    if tid is None:
        print("demo-po-change: the demo company is missing; run make demo-reset", file=sys.stderr)
        return 1
    with session(tid, engine) as s:
        ctrl = s.scalar(select(Membership.user_id).where(Membership.role == "controller"))
        run, _ = request_sync(s, tid, ctrl, "date_range", date(2026, 8, 1), date(2026, 10, 31))
        run_id = run.id
    state = execute_sync(engine, tid, run_id, RecordedQboReader(CHANGED), settings.qbo_page_size)
    print(f"demo-po-change: QuickBooks read {state} (recorded responses after a change)")
    print("  open purchase order 4471 or 4390 in the web app: the banner shows what changed;")
    print(
        "  the running worker re-matches the affected lines; FF-1003 is then 'possibly credited' (VC-DEMO-9)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
