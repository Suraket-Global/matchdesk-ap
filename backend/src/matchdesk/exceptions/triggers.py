"""Match-run triggers (T-4.1.6 (a); TRD 8.5 last paragraph).

A new or corrected document, a receiving commit or void, an approved late receipt, an alias or
tolerance change, a duplicate decision and a QuickBooks sync each request a run for the invoices
whose inputs changed. The scope is every uploaded invoice and credit note of the affected vendors,
because a run's input fingerprint covers the vendor's whole history; a document added on an in-scope
PO therefore re-evaluates the others too (the result depends only on the set of inputs, never on
arrival order). Modules that may not import ``exceptions`` (``qbo``,
``intake``) enqueue a ``match_request`` job instead, handled here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.exceptions.models import MatchRun
from matchdesk.exceptions.runs import request_run
from matchdesk.intake.models import InvoiceRow, live_invoice
from matchdesk.qbo import processing_allowed
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow

TASK = "match_request"


def _vendor_invoices(s: Session, vendor_ids: set[uuid.UUID]) -> list[uuid.UUID]:
    if not vendor_ids:
        return []
    return sorted(
        s.scalars(select(InvoiceRow.id).where(InvoiceRow.vendor_id.in_(vendor_ids), live_invoice())).all()
    )


def invoices_on_pos(s: Session, po_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Every invoice of the vendors of these purchase orders. The input fingerprint of a run covers
    the vendor's whole document history (no date filter, AD-13), so a narrower scope would leave the
    vendor's other invoices stale on read (found with the B3 demo data: an invoice naming an unknown
    PO stayed stale after a sync)."""
    ids = sorted({uuid.UUID(str(p)) for p in po_ids})
    if not ids:
        return []
    vendors = set(s.scalars(select(PurchaseOrderRow.vendor_id).where(PurchaseOrderRow.id.in_(ids))).all())
    return _vendor_invoices(s, vendors)


def invoices_on_po_lines(s: Session, po_line_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    ids = sorted({uuid.UUID(str(p)) for p in po_line_ids})
    if not ids:
        return []
    po_ids = s.scalars(select(PoLineRow.purchase_order_id).where(PoLineRow.id.in_(ids)).distinct()).all()
    return invoices_on_pos(s, po_ids)


def related_invoices(s: Session, invoice_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """The given invoices plus every invoice of their vendors (same reason as ``invoices_on_pos``);
    a deleted document is never in scope (B12)."""
    ids = sorted({uuid.UUID(str(i)) for i in invoice_ids})
    vendors = set(s.scalars(select(InvoiceRow.vendor_id).where(InvoiceRow.id.in_(ids))).all()) - {None}
    live = set(s.scalars(select(InvoiceRow.id).where(InvoiceRow.id.in_(ids), live_invoice())).all())
    return sorted(live | set(_vendor_invoices(s, vendors)))  # type: ignore[arg-type]


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
