"""Read-side context for the web app's screens (B4). Wiring only: every rule stays in its module.

The B3 endpoints returned identifiers; the screens of App-flow.md need the words beside them
(vendor, document and PO number, item code, age) and, in the match view (S-09, DD-01), the
evidence one decision rests on: the PO line, each receipt line with file, row and class, earlier
invoices on the same PO line, the QuickBooks billed quantity shown as "not counted", and the
calculation written from the values the rule engine stored. Nothing here decides a match.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.core import round_cents
from matchdesk.exceptions import describe_tolerance
from matchdesk.exceptions.models import ExceptionRow, ItemAlias, LineMatch, ToleranceRule
from matchdesk.identity import User
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.matching import ReceiptLine, receipt_line_counts
from matchdesk.qbo.models import Item, PoLineRow, PurchaseOrderRow, QboBillLineRow, QboBillRow, Vendor
from matchdesk.receiving import as_import
from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow

CLASS_WORDS = {"A": "warehouse record", "B": "signed delivery document", "C": "supplier document only"}


def qty(value: Decimal | None) -> str | None:
    """A quantity without trailing zeros (60.0000 -> 60), never through a float."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text


def price_text(value: Decimal | None) -> str | None:
    """A unit price with its cents kept (4.2000 -> 4.20, 0.0750 -> 0.075), never through a float."""
    text = qty(value)
    if text is None:
        return None
    whole, _, frac = text.partition(".")
    return f"{whole}.{frac.ljust(2, '0')}"


def vendor_names(s: Session) -> dict[uuid.UUID, str]:
    return dict(s.execute(select(Vendor.id, Vendor.name)).all())  # type: ignore[arg-type]


def user_names(s: Session, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = s.execute(select(User.id, User.display_name, User.email).where(User.id.in_(wanted))).all()
    return {uid: (name or email) for uid, name, email in rows}


def exception_context(s: Session, rows: list[ExceptionRow]) -> dict[uuid.UUID, dict[str, Any]]:
    """Words for the queue columns of S-08: vendor, document and PO number, item, age."""
    inv_ids = {e.invoice_id for e in rows}
    line_ids = {e.invoice_line_id for e in rows if e.invoice_line_id}
    invoices = {i.id: i for i in s.scalars(select(InvoiceRow).where(InvoiceRow.id.in_(inv_ids)))}
    lines = {ln.id: ln for ln in s.scalars(select(InvoiceLineRow).where(InvoiceLineRow.id.in_(line_ids)))}
    names = vendor_names(s)
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for e in rows:
        inv = invoices.get(e.invoice_id)
        ln = lines.get(e.invoice_line_id) if e.invoice_line_id else None
        out[e.id] = {
            "vendor_id": str(inv.vendor_id) if inv and inv.vendor_id else None,
            "vendor_name": names.get(inv.vendor_id) if inv and inv.vendor_id else None,
            "doc_number": inv.doc_number if inv else None,
            "doc_type": inv.doc_type if inv else None,
            "doc_date": inv.doc_date.isoformat() if inv and inv.doc_date else None,
            "po_number": inv.po_number_read if inv else None,
            "line_no": ln.line_no if ln else None,
            "supplier_item_code": ln.supplier_item_code if ln else None,
            "description": ln.description if ln else None,
            "line_amount": str(ln.amount) if ln and ln.amount is not None else None,
            "raised_at": e.created_at.isoformat(),
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
        }
    return out


def calculation(
    lm: LineMatch,
    tol: dict[str, Any],
    uom: str | None,
    has_receipt_rows: bool,
    qty_po: Decimal | None = None,
) -> str:
    """The calculation sentence of S-09 (design.md section 6), from the stored result values."""
    unit = f" {uom}" if uom else ""
    invoiced = lm.qty_invoiced_cum_net
    parts: list[str] = []
    if lm.receipt_line_count == 0:
        parts.append(
            "No counting receiving record for this PO line"
            + (" (rows that do not count are listed above)." if has_receipt_rows else ".")
        )
        parts.append("Received to date 0.")
    else:
        parts.append(f"Received to date {qty(lm.qty_received_cum)}{unit}.")
    if invoiced is not None:
        parts.append(f"Invoiced to date {qty(invoiced)}{unit} (net of credit notes).")
    received = lm.qty_received_cum or Decimal("0")
    price = lm.po_unit_price
    if invoiced is not None and lm.receipt_line_count > 0 and invoiced > received and price is not None:
        excess = invoiced - received
        parts.append(f"Excess {qty(excess)} × {price_text(price)} = {round_cents(excess * price)}.")
    if lm.qty_ordered is not None and invoiced is not None and invoiced > lm.qty_ordered:
        parts.append(
            f"Ordered {qty(lm.qty_ordered)}{unit}, so {qty(invoiced - lm.qty_ordered)} above the order."
        )
    if (
        lm.invoice_unit_price_po_uom is not None
        and price is not None
        and lm.invoice_unit_price_po_uom != price
    ):
        diff = lm.invoice_unit_price_po_uom - price
        sign = "above" if diff > 0 else "below"
        text = (
            f"Invoice price {price_text(lm.invoice_unit_price_po_uom)}, PO price {price_text(price)}: "
            f"{price_text(abs(diff))} {sign} the PO"
        )
        if qty_po is not None and diff > 0:
            text += f"; {price_text(diff)} × {qty(qty_po)} = {round_cents(diff * qty_po)}"
        parts.append(text + ".")
    parts.append(
        f"Quantity tolerance {tol.get('qty_tolerance')}; price tolerance {tol.get('price_tol_abs')} "
        f"or {tol.get('price_tol_pct')}%."
    )
    return " ".join(parts)


def _receipt_rows(s: Session, po_line_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    if not po_line_ids:
        return {}
    rows = s.execute(
        select(ReceiptLineRow, ReceiptRow, ReceivingImportRow)
        .join(ReceiptRow, ReceiptRow.id == ReceiptLineRow.receipt_id)
        .join(ReceivingImportRow, ReceivingImportRow.id == ReceiptLineRow.receiving_import_id)
        .where(ReceiptLineRow.po_line_id.in_(po_line_ids))
        .order_by(ReceiptRow.received_date, ReceiptLineRow.source_row)
    ).all()
    doc_ids = {imp.document_id for _rl, _r, imp in rows}
    file_names = dict(
        s.execute(select(DocumentRow.id, DocumentRow.original_name).where(DocumentRow.id.in_(doc_ids))).all()
    )
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for rl, r, imp in rows:
        line = ReceiptLine(
            id=str(rl.id),
            import_id=str(rl.receiving_import_id),
            po_line_id=str(rl.po_line_id),
            qty_in_po_uom=rl.qty_in_po_uom,
            received_date=r.received_date,
            receiver_marks_recorded=bool(r.receiver_marks_present and r.receiver_name),
            added_after_exception=rl.added_after_exception,
            late_approved=rl.late_approved,
        )
        counts = receipt_line_counts(line, as_import(imp))
        if counts:
            why = None
        elif imp.state == "voided":
            why = "Import voided"
        elif imp.evidence_class == "C":
            why = "Supplier's packing slip. Not counted as a receipt."
        elif rl.added_after_exception and not rl.late_approved:
            why = "Waiting for controller approval"
        elif imp.evidence_class == "B" and not line.receiver_marks_recorded:
            why = "No receiver's signature or count marks recorded"
        else:
            why = "Not counted"
        out.setdefault(rl.po_line_id, []).append(
            {
                "id": str(rl.id),
                "received_date": r.received_date.isoformat(),
                "qty": qty(rl.qty_in_po_uom),
                "source_file": file_names.get(imp.document_id) or "receiving file",
                "source_row": rl.source_row,
                "receiving_import_id": str(imp.id),
                "evidence_class": imp.evidence_class,
                "evidence_words": CLASS_WORDS.get(imp.evidence_class, imp.evidence_class),
                "receiver_ref": r.receiver_ref,
                "counts": counts,
                "not_counted_reason": why,
            }
        )
    return out


def line_evidence(
    s: Session, inv: InvoiceRow, lines: list[InvoiceLineRow]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Evidence per invoice line for the three panes of S-09 (DD-01, DD-06)."""
    matches = {
        lm.invoice_line_id: lm
        for lm in s.scalars(
            select(LineMatch).where(
                LineMatch.invoice_line_id.in_([ln.id for ln in lines]), LineMatch.is_current.is_(True)
            )
        )
    }
    po_line_ids = [lm.po_line_id for lm in matches.values() if lm.po_line_id]
    po_lines = {pl.id: pl for pl in s.scalars(select(PoLineRow).where(PoLineRow.id.in_(po_line_ids)))}
    # Quantity billed against each PO line in QuickBooks, shown greyed and never counted as a
    # receipt (AD-05; App-flow S-09). Read from the synced bill lines when the PO line has no figure.
    billed: dict[uuid.UUID, Decimal] = {}
    for pl_id, q in s.execute(
        select(QboBillLineRow.po_line_id, func.sum(QboBillLineRow.qty))
        .join(QboBillRow, QboBillRow.id == QboBillLineRow.qbo_bill_id)
        .where(QboBillLineRow.po_line_id.in_(po_line_ids), QboBillRow.txn_type == "bill")
        .group_by(QboBillLineRow.po_line_id)
    ).all():
        if q is not None and pl_id is not None:
            billed[pl_id] = q
    pos = {
        po.id: po
        for po in s.scalars(
            select(PurchaseOrderRow).where(
                PurchaseOrderRow.id.in_({pl.purchase_order_id for pl in po_lines.values()})
            )
        )
    }
    items = {
        i.id: i
        for i in s.scalars(
            select(Item).where(Item.id.in_({pl.item_id for pl in po_lines.values() if pl.item_id}))
        )
    }
    aliases = {
        a.id: a
        for a in s.scalars(
            select(ItemAlias).where(ItemAlias.id.in_([lm.alias_id for lm in matches.values() if lm.alias_id]))
        )
    }
    rules = {
        t.id: t
        for t in s.scalars(
            select(ToleranceRule).where(
                ToleranceRule.id.in_(
                    [lm.tolerance_rule_id for lm in matches.values() if lm.tolerance_rule_id]
                )
            )
        )
    }
    receipts = _receipt_rows(s, po_line_ids)
    # Earlier invoices and credit notes on the same PO line (current results only), in document order.
    others = s.execute(
        select(LineMatch.po_line_id, InvoiceLineRow, InvoiceRow)
        .join(InvoiceLineRow, InvoiceLineRow.id == LineMatch.invoice_line_id)
        .join(InvoiceRow, InvoiceRow.id == InvoiceLineRow.invoice_id)
        .where(
            LineMatch.po_line_id.in_(po_line_ids),
            LineMatch.is_current.is_(True),
            InvoiceRow.id != inv.id,
        )
        .order_by(InvoiceRow.doc_date, InvoiceRow.doc_number_norm, InvoiceRow.file_order_key)
    ).all()
    history: dict[uuid.UUID, list[dict[str, Any]]] = {}
    doc_numbers: set[str] = set()
    for po_line_id, oln, oinv in others:
        if oinv.doc_number_norm:
            doc_numbers.add(oinv.doc_number_norm)
        history.setdefault(po_line_id, []).append(  # type: ignore[arg-type]
            {
                "invoice_id": str(oinv.id),
                "doc_type": oinv.doc_type,
                "doc_number": oinv.doc_number,
                "doc_date": oinv.doc_date.isoformat() if oinv.doc_date else None,
                "qty": qty(oln.qty),
                "source": "document",
            }
        )
    if inv.doc_number_norm:
        doc_numbers.add(inv.doc_number_norm)
    bills = s.execute(
        select(QboBillLineRow, QboBillRow)
        .join(QboBillRow, QboBillRow.id == QboBillLineRow.qbo_bill_id)
        .where(QboBillLineRow.po_line_id.in_(po_line_ids))
        .order_by(QboBillRow.txn_date, QboBillRow.doc_number)
    ).all()
    for bl, bill in bills:
        if bill.doc_number_norm and bill.doc_number_norm in doc_numbers:
            continue  # the document itself is listed; the bill is its ledger record
        history.setdefault(bl.po_line_id, []).append(  # type: ignore[arg-type]
            {
                "invoice_id": None,
                "doc_type": "credit_note" if bill.txn_type == "vendor_credit" else "invoice",
                "doc_number": bill.doc_number,
                "doc_date": bill.txn_date.isoformat() if bill.txn_date else None,
                "qty": qty(bl.qty),
                "source": "qbo_bill",
            }
        )
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for ln in lines:
        lm = matches.get(ln.id)
        if lm is None:
            out[ln.id] = {"match": None}
            continue
        pl = po_lines.get(lm.po_line_id) if lm.po_line_id else None
        po = pos.get(pl.purchase_order_id) if pl else None
        alias = aliases.get(lm.alias_id) if lm.alias_id else None
        tol = describe_tolerance(rules.get(lm.tolerance_rule_id) if lm.tolerance_rule_id else None)
        item = items.get(pl.item_id) if pl and pl.item_id else None
        rec = receipts.get(lm.po_line_id, []) if lm.po_line_id else []
        out[ln.id] = {
            "match": {
                "line_kind": lm.line_kind,
                "qty_ordered": qty(lm.qty_ordered),
                "qty_received_cum": qty(lm.qty_received_cum),
                "qty_invoiced_cum_net": qty(lm.qty_invoiced_cum_net),
                "qty_invoiced_prior_qbo": qty(lm.qty_invoiced_prior_qbo),
                "receipt_line_count": lm.receipt_line_count,
                "covered": lm.covered,
                "po_unit_price": qty(lm.po_unit_price),
                "invoice_unit_price_po_uom": qty(lm.invoice_unit_price_po_uom),
                "calculation": calculation(
                    lm,
                    tol,
                    pl.uom if pl else None,
                    bool(rec),
                    ln.qty * (alias.conversion_factor if alias else Decimal("1"))
                    if ln.qty is not None
                    else None,
                ),
            },
            "purchase_order": {
                "id": str(po.id),
                "po_number": po.po_number,
                "line_id": str(pl.id),
                "line_no": pl.line_no,
                "description": pl.description,
                "item_sku": item.sku if item else None,
                "item_name": item.name if item else None,
                "qty_ordered": qty(pl.qty_ordered),
                "uom": pl.uom,
                "unit_price": qty(pl.unit_price),
                "qbo_billed_qty": qty(
                    pl.qbo_billed_qty if pl.qbo_billed_qty is not None else billed.get(pl.id)
                ),
            }
            if pl and po
            else None,
            "alias": {
                "id": str(alias.id),
                "supplier_item_code": alias.supplier_item_code,
                "conversion_factor": qty(alias.conversion_factor),
                "supplier_uom": alias.supplier_uom,
                "item_uom": alias.item_uom,
                "status": alias.status,
            }
            if alias
            else None,
            "tolerance": tol,
            "receipts": rec,
            "history": history.get(lm.po_line_id, []) if lm.po_line_id else [],
        }
    return out


def bill_status(s: Session, inv: InvoiceRow) -> dict[str, Any] | None:
    """'paid' or 'unpaid' from the QuickBooks bill with the same vendor and number, if any."""
    if not inv.doc_number_norm or inv.vendor_id is None:
        return None
    bill = s.scalar(
        select(QboBillRow).where(
            QboBillRow.vendor_id == inv.vendor_id,
            QboBillRow.doc_number_norm == inv.doc_number_norm,
            QboBillRow.txn_type == "bill",
        )
    )
    if bill is None:
        return None
    return {"doc_number": bill.doc_number, "paid_status": bill.paid_status, "balance": str(bill.balance)}


__all__ = [
    "bill_status",
    "calculation",
    "exception_context",
    "line_evidence",
    "qty",
    "user_names",
    "vendor_names",
]
