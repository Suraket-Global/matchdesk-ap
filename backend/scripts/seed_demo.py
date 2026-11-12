"""OPS-04 companion: load one invented tenant so the whole flow can be played through (B3, B4).

Everything is synthetic: an invented distributor, a controller and a clerk with ``.invalid``
addresses, the invented suppliers of the recorded QuickBooks fixtures (read through a real sync
run over the recorded-response reader), the receiving attestation and supplier-item aliases (one
with a unit conversion waiting for the controller). From B4 the seed no longer uploads the
invoices or imports the receiving file: it writes them to ``play-files/`` at the repository root
so the owner does those steps in the web app (docs/PLAY.md). ``--preload`` restores the B3
behaviour (everything loaded and processed by the worker). ``--tag NAME`` creates a separate
tenant and addresses (``controller.NAME@example.invalid``) and writes the files to a temporary
folder outside the repository (``--files-dir`` chooses it); the end-to-end test uses it so it
never disturbs the owner's tenant and never leaves folders in ``play-files/``.
Sign in by requesting a link; Mailpit (http://127.0.0.1:8025) shows the mail. Refuses to run when
``MATCHDESK_ENV`` is ``production``. Idempotent: a second run finds the tenant and stops.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

from matchdesk.core import load_settings, text_pdf
from matchdesk.exceptions import create_alias
from matchdesk.identity import Membership, Tenant, User, issue_session, load_session
from matchdesk.intake import add_file, create_batch
from matchdesk.qbo import (
    DEFAULT_FIXTURES,
    FakeIntuitTokenEndpoint,
    RecordedQboReader,
    complete_callback,
    execute_sync,
    request_sync,
    start_authorization,
)
from matchdesk.qbo.models import Item, Vendor
from matchdesk.receiving import attest, commit, create_import, save_mapping, set_declaration
from matchdesk.tenancy import get_engine, global_session, session
from matchdesk.worker.__main__ import run_once

TENANT = "Demo Distributor Ltd (synthetic)"
CONTROLLER = "controller.demo@example.invalid"
CLERK = "clerk.demo@example.invalid"
ROOT = Path(__file__).resolve().parents[1]
PLAY_DIR = ROOT.parent / "play-files"

RECEIVING = """PO,Line,Qty,UOM,Received,Receiver
4390,1,500,,2026-08-20,R-0820
4390,2,500,,2026-08-20,R-0820
4471,1,60,,2026-09-04,R-0904
4502,1,40,,2026-10-03,R-1003
4510,1,1000,,2026-10-06,R-1006
4520,1,200,,2026-10-09,R-1009
4540,1,900,,2026-10-16,R-1016
4999,1,10,,2026-10-28,R-1028
"""

# (vendor, number, date, PO, [(code, description, qty, uom, price)], extra lines, printed total or None)
INVOICES = [
    (
        "Fictional Fasteners Ltd",
        "FF-1001",
        "2026-10-02",
        "4390",
        [("HB-M8", "Hex bolt M8", 250, "EA", "0.42")],
        [],
        None,
    ),
    (
        "Fictional Fasteners Ltd",
        "FF-1002",
        "2026-10-02",
        "4390",
        [("WS-M8", "Washer M8", 500, "EA", "0.08")],
        [],
        None,
    ),
    (
        "Fictional Fasteners Ltd",
        "FF-1003",
        "2026-10-07",
        "4471",
        [("HB-M8", "Hex bolt M8", 100, "EA", "4.20")],
        [],
        None,
    ),
    (
        "Fictional Fasteners Ltd",
        "FF-1004",
        "2026-10-20",
        "4540",
        [("WS-M8", "Washer M8", 1000, "EA", "0.08")],
        [],
        None,
    ),
    (
        "Synthetic Supply Co",
        "SS-5102",
        "2026-10-07",
        "4510",
        [("TIE-200", "Cable tie 200 mm", 1000, "EA", "0.05")],
        [],
        None,
    ),
    (
        "Synthetic Supply Co",
        "SS-5110",
        "2026-10-04",
        "4502",
        [("PW-500", "Pallet wrap 500 mm", 40, "EA", "18.95")],
        ["FREIGHT   Delivery                                   25.00"],
        None,
    ),
    (
        "Synthetic Supply Co",
        "SS-5111",
        "2026-10-21",
        "4502",
        [("PW-500", "Pallet wrap 500 mm", 40, "EA", "18.50")],
        [],
        None,
    ),
    (
        "Imaginary Packaging Inc",
        "IP-301",
        "2026-10-10",
        "4520",
        [("CT-25", "Carton 12x12 case of 25", 8, "CS", "27.50")],
        [],
        None,
    ),
    (
        "Imaginary Packaging Inc",
        "IP-302",
        "2026-10-14",
        "4533",
        [("CT-25", "Carton 12x12 case of 25", 4, "CS", "27.50")],
        [],
        None,
    ),
    (
        "Fictional Fasteners Ltd",
        "FF-1006",
        "2026-10-22",
        "4540",
        [("WS-M8", "Washer M8", 10, "EA", "0.08")],
        [],
        "8.00",
    ),
    (None, "SS-5120", "2026-10-23", "4510", [("TIE-200", "Cable tie 200 mm", 10, "EA", "0.05")], [], None),
    (
        "Fictional Fasteners Ltd",
        "FF-1007",
        "2026-10-28",
        "4999",
        [("HB-M8", "Hex bolt M8", 10, "EA", "0.42")],
        [],
        None,
    ),
]


def invoice_pdf(
    vendor: str | None,
    number: str,
    day: str,
    po: str,
    items: list,
    extra: list[str],
    printed_total: str | None,
) -> bytes:
    lines = ["INVOICE", "Synthetic document generated for the MatchDesk demo. Not a real invoice.", ""]
    if vendor:
        lines.append(f"Vendor: {vendor}")
    lines += [f"Invoice No: {number}", f"Invoice Date: {day}", f"PO Number: {po}", "Currency: CAD", ""]
    subtotal = Decimal("0")
    for code, desc, qty, uom, price in items:
        amount = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
        subtotal += amount
        lines.append(f"{code:<9} {desc:<26} {qty:>6} {uom:<3} {price:>8} {amount:>10}")
    for ln in extra:
        lines.append(ln)
        subtotal += Decimal(ln.split()[-1])
    tax = Decimal("0.00")
    lines += [
        "",
        f"Subtotal: {subtotal:.2f}",
        f"Tax: {tax:.2f}",
        f"Total: {printed_total or f'{subtotal + tax:.2f}'}",
    ]
    return text_pdf(lines, title=f"Invoice {number}")


def write_play_files(folder: Path) -> list[tuple[str, bytes]]:
    """The invented files the owner uploads in the web app (docs/PLAY.md)."""
    (folder / "invoices").mkdir(parents=True, exist_ok=True)
    (folder / "receiving-warehouse-log.csv").write_bytes(RECEIVING.encode())
    files = [(f"{spec[1]}.pdf", invoice_pdf(*spec)) for spec in INVOICES]
    # One byte-identical repeat: shown as a duplicate file, never processed twice.
    files.append(("FF-1002 copy.pdf", invoice_pdf(*INVOICES[1])))
    for name, data in files:
        (folder / "invoices" / name).write_bytes(data)
    (folder / "README.txt").write_text(
        "Invented files for the MatchDesk demo (docs/PLAY.md). Not real documents.\n"
        "invoices/: 13 invoice PDFs, one of them a byte-identical copy.\n"
        "receiving-warehouse-log.csv: the warehouse receiving log (class A).\n"
    )
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", help="separate tenant, addresses and play-files folder", default=None)
    ap.add_argument("--preload", action="store_true", help="also upload and process everything (B3)")
    ap.add_argument(
        "--files-dir",
        help="where to write the play files (default: play-files/, or a temporary folder with --tag)",
    )
    args = ap.parse_args()
    tag = args.tag
    if tag is not None and not tag.replace("-", "").isalnum():
        print("seed-demo: --tag takes letters, digits and dashes", file=sys.stderr)
        return 2
    tenant_name = TENANT if tag is None else f"{TENANT} {tag}"
    controller = CONTROLLER if tag is None else f"controller.{tag}@example.invalid"
    clerk = CLERK if tag is None else f"clerk.{tag}@example.invalid"
    if args.files_dir:
        folder = Path(args.files_dir)
    else:
        folder = PLAY_DIR if tag is None else Path(tempfile.gettempdir()) / f"matchdesk-play-{tag}"
    settings = load_settings()
    if settings.env == "production":
        print("seed-demo: refused, MATCHDESK_ENV is production", file=sys.stderr)
        return 1
    files = write_play_files(folder)
    env = {**os.environ, "MATCHDESK_MIGRATION_DATABASE_URL": settings.migration_database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = get_engine(settings.database_url)
    if tag is not None:
        # A tagged run is an automated test run from 127.0.0.1: it starts with the local sign-in
        # counters empty, so earlier runs within the hour do not reach the per-address limit (the
        # owner's untagged seed and production never do this; make demo-reset clears them too).
        with global_session(engine) as s:
            s.execute(text("delete from auth_rate_events"))
    with global_session(engine) as s:
        if s.scalar(select(Tenant).where(Tenant.name == tenant_name)) is not None:
            print(f"seed-demo: '{tenant_name}' already exists; nothing changed")
            print(f"  controller: {controller}   clerk: {clerk}   play files: {folder}")
            print("  for a clean start: make demo-reset")
            return 0
        t = Tenant(name=tenant_name)
        s.add(t)
        users = {}
        for email, name in ((controller, "Demo Controller"), (clerk, "Demo Clerk")):
            u = s.scalar(select(User).where(User.email == email)) or User(email=email, display_name=name)
            s.add(u)
            users[email] = u
        s.flush()
        tid, ctrl_id, clerk_id = t.id, users[controller].id, users[clerk].id
    with session(tid, engine) as s:
        s.add_all(
            [
                Membership(tenant_id=tid, user_id=ctrl_id, role="controller"),
                Membership(tenant_id=tid, user_id=clerk_id, role="clerk"),
            ]
        )

    # QuickBooks: connect through the fake authorisation server, then a real sync run over the
    # recorded synthetic responses (shape unverified until T-1.1.1).
    endpoint = FakeIntuitTokenEndpoint()
    token = issue_session(engine, ctrl_id, tid)
    ctx = load_session(engine, token)
    assert ctx is not None
    with session(tid, engine) as s:
        url = start_authorization(s, settings, tid, ctrl_id, ctx.session_id)
    state = url.split("state=")[1].split("&")[0]
    with session(tid, engine) as s:
        complete_callback(
            s,
            settings,
            endpoint,
            tid,
            ctx.session_id,
            state,
            endpoint.issue_code(),
            f"demo-realm-{tid}",
            "Demo Distributor Ltd (synthetic)",
        )
        run, _ = request_sync(s, tid, ctrl_id, "date_range", date(2026, 8, 1), date(2026, 10, 31))
    execute_sync(engine, tid, run.id, RecordedQboReader(DEFAULT_FIXTURES), settings.qbo_page_size)

    with session(tid, engine) as s:
        vendors = {v.qbo_id: v.id for v in s.scalars(select(Vendor))}
        items = {i.sku: i.id for i in s.scalars(select(Item))}
        for vq, code, sku, factor, sup, itm in (
            ("56", "HB-M8", "HB-M8", "1", None, None),
            ("56", "WS-M8", "WS-M8", "1", None, None),
            ("57", "PW-500", "PW-500", "1", None, None),
            ("57", "TIE-200", "TIE-200", "1", None, None),
            ("58", "CT-25", "CT-1212", "25", "CS", "EA"),  # a conversion: waits for the controller
        ):
            create_alias(s, tid, clerk_id, vendors[vq], code, items[sku], Decimal(factor), sup, itm)
        attest(s, tid, ctrl_id, "A", "Warehouse receiving log kept by the receiver (synthetic)", [])
    processed = 0
    if args.preload:
        with session(tid, engine) as s:
            imp, _preview = create_import(
                s,
                tid,
                clerk_id,
                RECEIVING.encode(),
                "spreadsheet",
                "A",
                "Demo Receiver",
                "receiving-warehouse-log.csv",
            )
            set_declaration(s, imp, clerk_id, True, date(2026, 8, 1), date(2026, 11, 14), "Demo Receiver")
            save_mapping(
                s,
                imp,
                clerk_id,
                {
                    "po_number": "PO",
                    "line_no": "Line",
                    "qty_received": "Qty",
                    "uom": "UOM",
                    "received_date": "Received",
                    "receiver_ref": "Receiver",
                },
                "Warehouse log",
            )
            commit(s, imp, clerk_id, frozenset())
            batch = create_batch(s, tid)
            for n, (name, data) in enumerate(files):
                add_file(s, tid, clerk_id, batch.id, f"demo-{n}", data, "application/pdf", name)
        while run_once(engine) is not None:
            processed += 1
    with session(tid, engine) as s:
        from matchdesk.exceptions.models import ExceptionRow

        open_excs = s.scalar(
            select(func.count()).select_from(ExceptionRow).where(ExceptionRow.status == "open")
        )
    print(f"seed-demo: tenant '{tenant_name}' ({tid})")
    print(f"  controller: {controller}   clerk: {clerk}")
    print("  sign in: open the web app (make web, http://127.0.0.1:5173), ask for a link,")
    print("           then open it from Mailpit (http://127.0.0.1:8025)")
    print(f"  play files: {folder} (receiving log and 13 invoice PDFs; see docs/PLAY.md)")
    if args.preload:
        print(f"  preloaded: {len(files)} files uploaded, {processed} jobs run, {open_excs} open exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
