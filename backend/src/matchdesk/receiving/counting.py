"""Counting receiving evidence per PO line, for read screens (S-10). The rule itself is
``matching.receipt_line_counts``; this only feeds it database rows."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.matching import EvidenceClass, ReceiptLine, ReceivingImport, receipt_line_counts
from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow


def as_import(i: ReceivingImportRow) -> ReceivingImport:
    return ReceivingImport(
        id=str(i.id),
        evidence_class=EvidenceClass(i.evidence_class),
        committed=i.state in {"succeeded", "voided"},
        voided=i.state == "voided",
        declared_complete=i.declared_complete,
        coverage_start=i.coverage_start,
        coverage_end=i.coverage_end,
    )


def counting_receipt_totals(
    s: Session, po_line_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, tuple[Decimal, int]]:
    """PO line id -> (net counting quantity in PO units, number of counting lines)."""
    ids = list(po_line_ids)
    if not ids:
        return {}
    rows = s.execute(
        select(ReceiptLineRow, ReceiptRow, ReceivingImportRow)
        .join(
            ReceiptRow,
            (ReceiptRow.id == ReceiptLineRow.receipt_id) & (ReceiptRow.tenant_id == ReceiptLineRow.tenant_id),
        )
        .join(
            ReceivingImportRow,
            (ReceivingImportRow.id == ReceiptLineRow.receiving_import_id)
            & (ReceivingImportRow.tenant_id == ReceiptLineRow.tenant_id),
        )
        .where(ReceiptLineRow.po_line_id.in_(ids))
    ).all()
    out: dict[uuid.UUID, tuple[Decimal, int]] = {}
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
        if receipt_line_counts(line, as_import(imp)):
            qty, n = out.get(rl.po_line_id, (Decimal("0"), 0))
            out[rl.po_line_id] = (qty + rl.qty_in_po_uom, n + 1)
    return out
