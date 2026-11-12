"""Match-run triggers (T-4.1.6 (a); TRD 8.5 last paragraph).

A new or corrected document, a receiving commit or void, an approved late receipt, an alias or
tolerance change, a duplicate decision and a QuickBooks sync each request a run for the invoices
whose inputs changed. The scope is every uploaded invoice and credit note on the affected purchase
orders, so a document added on an in-scope PO re-evaluates the others too (the result depends only
on the set of inputs, never on arrival order). Modules that may not import ``exceptions`` (``qbo``,
``intake``) enqueue a ``match_request`` job instead, handled here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from matchdesk.exceptions.models import MatchRun
from matchdesk.exceptions.runs import request_run
from matchdesk.intake.models import InvoiceRow
from matchdesk.matching import normalise_number
from matchdesk.qbo import processing_allowed
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow

TASK = "match_request"


def invoices_on_pos(s: Session, po_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    ids = sorted({uuid.UUID(str(p)) for p in po_ids})
    if not ids:
        return []
    keys = s.execute(
        select(PurchaseOrderRow.vendor_id, PurchaseOrderRow.po_number_norm).where(
            PurchaseOrderRow.id.in_(ids)
        )
    ).all()
    invs = s.scalars(select(InvoiceRow).where(InvoiceRow.vendor_id.in_({k[0] for k in keys}))).all()
    wanted = {(k[0], k[1]) for k in keys}
    return sorted(
        i.id
        for i in invs
        if i.purchase_order_id in ids or (i.vendor_id, normalise_number(i.po_number_read)) in wanted
    )


def invoices_on_po_lines(s: Session, po_line_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    ids = sorted({uuid.UUID(str(p)) for p in po_line_ids})
    if not ids:
        return []
    po_ids = s.scalars(select(PoLineRow.purchase_order_id).where(PoLineRow.id.in_(ids)).distinct()).all()
    return invoices_on_pos(s, po_ids)


def related_invoices(s: Session, invoice_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """The given invoices plus every invoice on the purchase orders they name."""
    ids = sorted({uuid.UUID(str(i)) for i in invoice_ids})
    rows = s.scalars(select(InvoiceRow).where(InvoiceRow.id.in_(ids))).all()
    refs = [
        (r.vendor_id, normalise_number(r.po_number_read)) for r in rows if r.vendor_id and r.po_number_read
    ]
    po_ids = {r.purchase_order_id for r in rows if r.purchase_order_id}
    if refs:
        po_ids |= set(
            s.scalars(
                select(PurchaseOrderRow.id).where(
                    tuple_(PurchaseOrderRow.vendor_id, PurchaseOrderRow.po_number_norm).in_(refs)
                )
            ).all()
        )
    return sorted(set(ids) | set(invoices_on_pos(s, po_ids)))


def request_runs(
    s: Session,
    tenant_id: uuid.UUID,
    invoice_ids: Iterable[uuid.UUID],
    trigger: str,
    trigger_ref: uuid.UUID | None = None,
) -> MatchRun | None:
    ids = sorted({uuid.UUID(str(i)) for i in invoice_ids})
    if not ids:
        return None
    run, _created = request_run(s, tenant_id, ids, trigger=trigger, trigger_ref=trigger_ref)
    return run


def handle_match_request(s: Session, payload: dict[str, Any]) -> None:
    """Worker handler for ``match_request`` jobs enqueued by ``qbo`` (sync) and ``intake`` (document
    ready). Runs inside the job wrapper's tenant session."""
    tenant_id = uuid.UUID(payload["tenant_id"])
    ids: set[uuid.UUID] = set()
    if payload.get("po_ids"):
        ids |= set(invoices_on_pos(s, payload["po_ids"]))
    if payload.get("invoice_ids"):
        ids |= set(related_invoices(s, payload["invoice_ids"]))
    ref = payload.get("trigger_ref")
    if not processing_allowed(s):
        return  # disconnected: no match run on QuickBooks-derived rows (self-check 6.4)
    request_runs(s, tenant_id, ids, payload.get("trigger", "manual"), uuid.UUID(ref) if ref else None)
