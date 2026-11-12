"""Turn an extraction run into invoice and credit-note rows (T-3.3.2 (a), (d); MH-05; B3).

A file may hold several documents (``output["invoices"]``, each with ``page_from``); otherwise the
output is one document. Every value is stored as read, with provenance ``read``; nothing is
inferred. The vendor is identified only by an exact normalised name match to one QuickBooks vendor,
and the purchase order only by vendor and normalised number; anything else stays empty for review.
A document that passed every gate requests a match run; one that failed waits for a person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from matchdesk.core import dec
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow, UsageEvent
from matchdesk.matching import normalise_number
from matchdesk.qbo.models import PurchaseOrderRow, Vendor
from matchdesk.tenancy import enqueue

MATCH_REQUEST_TASK = "match_request"  # handled by ``exceptions`` (intake does not import it)
HEADER_FIELDS = (
    "doc_type",
    "vendor_name",
    "doc_number",
    "doc_date",
    "po_number",
    "currency",
    "subtotal",
    "tax_total",
    "total",
    "references_invoice_number",
)
LINE_FIELDS = ("supplier_item_code", "description", "qty", "uom", "unit_price", "amount", "kind")


PACIFIC = ZoneInfo("America/Vancouver")


def usage_month(at: datetime) -> date:
    """First day of the month, Pacific time, of the moment ``at`` (schema.md usage_events)."""
    local = at.astimezone(PACIFIC)
    return date(local.year, local.month, 1)


def record_usage(
    s: Session,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    rows: list[InvoiceRow],
    at: datetime | None = None,
) -> None:
    """One billable unit per invoice or credit note, in the month it was first extracted. A second
    extraction or a re-match never adds one (unique per invoice; IT-26)."""
    month = usage_month(at or datetime.now(UTC))
    for inv in rows:
        s.execute(
            pg_insert(UsageEvent)
            .values(
                tenant_id=tenant_id,
                invoice_id=inv.id,
                document_id=document_id,
                unit_month=month,
                kind=inv.doc_type if inv.doc_type in ("invoice", "credit_note") else "invoice",
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "invoice_id"])
        )


def _name(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def identify_vendor(s: Session, name: str | None) -> uuid.UUID | None:
    if not name:
        return None
    wanted = _name(name)
    hits = [v.id for v in s.scalars(select(Vendor)) if _name(v.name) == wanted]
    return hits[0] if len(hits) == 1 else None


def link_po(s: Session, vendor_id: uuid.UUID | None, po_number: str | None) -> uuid.UUID | None:
    if vendor_id is None or not po_number:
        return None
    hits = s.scalars(
        select(PurchaseOrderRow.id).where(
            PurchaseOrderRow.vendor_id == vendor_id,
            PurchaseOrderRow.po_number_norm == normalise_number(po_number),
        )
    ).all()
    return hits[0] if len(hits) == 1 else None


def _d(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return dec(str(value))


def _day(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def materialise(
    s: Session,
    tenant_id: uuid.UUID,
    doc: DocumentRow,
    run_id: uuid.UUID,
    output: dict[str, Any],
    passed: bool,
) -> list[InvoiceRow]:
    existing = s.scalars(select(InvoiceRow).where(InvoiceRow.document_id == doc.id)).all()
    if existing:
        return list(existing)  # a document's invoices are created once; corrections go through review
    parts = output.get("invoices") or [output]
    rows: list[InvoiceRow] = []
    for n, part in enumerate(parts):
        vendor_id = identify_vendor(s, part.get("vendor_name"))
        doc_type = part.get("doc_type") if part.get("doc_type") in ("invoice", "credit_note") else "invoice"
        page_from = int(part.get("page_from") or (n + 1))
        inv = InvoiceRow(
            tenant_id=tenant_id,
            document_id=doc.id,
            page_from=page_from,
            page_to=int(part.get("page_to") or page_from),
            file_order_key=doc.sha256,
            doc_type=doc_type,
            vendor_id=vendor_id,
            vendor_name_read=part.get("vendor_name"),
            doc_number=part.get("doc_number"),
            doc_number_norm=normalise_number(part.get("doc_number")) or None,
            doc_date=_day(part.get("doc_date")),
            po_number_read=part.get("po_number"),
            purchase_order_id=link_po(s, vendor_id, part.get("po_number")),
            references_invoice_number=part.get("references_invoice_number"),
            subtotal=_d(part.get("subtotal")),
            tax_total=_d(part.get("tax_total")),
            total=_d(part.get("total")),
            currency=part.get("currency"),
            verification_status="passed" if passed else "failed",
            extraction_run_id=run_id,
            field_sources={f: {"source": "read"} for f in HEADER_FIELDS if part.get(f) is not None},
            version=1,
        )
        s.add(inv)
        s.flush()
        for i, ln in enumerate(part.get("lines", []), start=1):
            kind = ln.get("kind") if ln.get("kind") in ("item", "freight", "fee", "discount") else "item"
            s.add(
                InvoiceLineRow(
                    tenant_id=tenant_id,
                    invoice_id=inv.id,
                    line_no=int(ln.get("line_no") or i),
                    supplier_item_code=ln.get("supplier_item_code"),
                    description=ln.get("description"),
                    qty=_d(ln.get("qty")),
                    uom=ln.get("uom"),
                    unit_price=_d(ln.get("unit_price")),
                    amount=_d(ln.get("amount")),
                    line_kind=kind,
                    page_no=ln.get("page_no"),
                    field_sources={f: {"source": "read"} for f in LINE_FIELDS if ln.get(f) is not None},
                )
            )
        rows.append(inv)
    s.flush()
    record_usage(s, tenant_id, doc.id, rows)
    if passed and rows:
        enqueue(
            s,
            MATCH_REQUEST_TASK,
            tenant_id,
            {
                "invoice_ids": [str(r.id) for r in rows],
                "trigger": "document_ready",
                "trigger_ref": str(doc.id),
            },
            str(doc.correlation_id),
        )
    return rows
