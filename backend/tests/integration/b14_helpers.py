"""Shared helpers of the B14 acceptance tests (2026-11-17). All data synthetic."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date
from decimal import Decimal as D

from sqlalchemy import select, text

from matchdesk.exceptions import stale_runs
from matchdesk.exceptions.models import ExceptionRow, ItemAlias, LineMatch
from matchdesk.matching import normalise_code, normalise_number
from matchdesk.qbo.models import Item, PoLineRow, PurchaseOrderRow, QboBillRow, Vendor
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import NOW, World

OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def match(client, engine, headers, ids) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(i) for i in ids]}, headers=headers)
    assert r.status_code in (200, 202), r.text
    drain(engine)


def excs(engine, w, invoice_id) -> list[ExceptionRow]:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        return list(s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id == invoice_id)).all())


def exc_of(engine, w, invoice_id, typ: str) -> ExceptionRow:  # type: ignore[no-untyped-def]
    return next(e for e in excs(engine, w, invoice_id) if e.type == typ)


def second_supplier(engine, w: World, n: int = 2, ordered: str = "100") -> World:  # type: ignore[no-untyped-def]
    """Another synthetic supplier with its own purchase order 4471 and alias, in the same account.
    The returned world shares the invoice and document maps and the receiving import of ``w``."""
    with session(w.tenant_id, engine) as s:
        v = Vendor(tenant_id=w.tenant_id, qbo_id=f"V{n}", name=f"Synthetic Supplier {n}", synced_at=NOW)
        it = Item(tenant_id=w.tenant_id, qbo_id=f"I{n}", name=f"Synthetic part {n}", synced_at=NOW)
        s.add_all([v, it])
        s.flush()
        po = PurchaseOrderRow(
            tenant_id=w.tenant_id,
            qbo_id=f"PO{n}",
            vendor_id=v.id,
            po_number="4471",
            po_number_norm=normalise_number("4471"),
            txn_date=date(2026, 9, 1),
            synced_at=NOW,
        )
        s.add(po)
        s.flush()
        pl = PoLineRow(
            tenant_id=w.tenant_id,
            purchase_order_id=po.id,
            qbo_line_id="2",
            line_no=2,
            item_id=it.id,
            qty_ordered=D(ordered),
            uom="EA",
            unit_price=D("4.20"),
        )
        al = ItemAlias(
            tenant_id=w.tenant_id,
            vendor_id=v.id,
            supplier_item_code="W-100",
            supplier_item_code_norm=normalise_code("W-100"),
            item_id=it.id,
            status="active",
            created_by=w.user_id,
        )
        s.add_all([pl, al])
        s.flush()
        return dataclasses.replace(
            w, vendor_id=v.id, item_id=it.id, po_id=po.id, po_line_id=pl.id, alias_id=al.id
        )


def vendor_credit(engine, w: World, total: str, day: date, number: str = "VC-9") -> uuid.UUID:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        vc = QboBillRow(
            tenant_id=w.tenant_id,
            qbo_id=f"VC-{uuid.uuid4().hex[:6]}",
            txn_type="vendor_credit",
            vendor_id=w.vendor_id,
            doc_number=number,
            doc_number_norm=normalise_number(number),
            txn_date=day,
            total=D(total),
            synced_at=NOW,
        )
        s.add(vc)
        s.flush()
        return vc.id


def out_of_date(engine, w: World) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    """Invoice lines whose current result is out of date, or that have no current result at all
    although their document is live and verified. Empty when nothing is out of date."""
    with session(w.tenant_id, engine) as s:
        current = s.execute(
            select(LineMatch.invoice_line_id, LineMatch.match_run_id).where(LineMatch.is_current.is_(True))
        ).all()
        stale = stale_runs(s, list({r[1] for r in current}))
        return sorted(line for line, run in current if stale.get(run))


def pending_jobs(engine, w: World) -> int:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        return int(
            s.execute(
                text(
                    "select count(*) from job_queue where state in ('queued', 'running') "
                    "and payload->>'tenant_id' = :t"
                ),
                {"t": str(w.tenant_id)},
            ).scalar_one()
        )


def settled(engine, w: World) -> None:  # type: ignore[no-untyped-def]
    """The C1 invariant: once the worker has drained, no result is out of date and nothing waits."""
    drain(engine)
    assert pending_jobs(engine, w) == 0
    assert out_of_date(engine, w) == []
