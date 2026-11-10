"""Assemble a ``MatchInput`` from the database for a scope of test documents (T-4.1.6 (a)).

No date filter is applied to purchase-order history, receipts, earlier invoices,
bills or credits (CLAUDE.md prohibited shortcuts; AD-13). Rows are read through
the caller's tenant session, so row-level security bounds everything.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from matchdesk.exceptions.models import ExceptionRow, ItemAlias, ToleranceRule
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.matching import (
    Alias,
    AliasStatus,
    DocLine,
    DocType,
    Document,
    DuplicateDecision,
    EvidenceClass,
    LineKind,
    MatchInput,
    PoLine,
    PurchaseOrder,
    QboBill,
    QboBillLine,
    ReceiptLine,
    ReceivingImport,
    Tolerance,
    VerificationStatus,
    normalise_number,
)
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow, QboBillLineRow, QboBillRow
from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow


def _s(v: uuid.UUID | None) -> str | None:
    return str(v) if v is not None else None


def build_match_input(
    s: Session, test_invoice_ids: Iterable[uuid.UUID], tenant_currency: str = "CAD", ruleset_code: str = "v1"
) -> MatchInput:
    test_ids = sorted({uuid.UUID(str(i)) for i in test_invoice_ids})
    tests = s.scalars(select(InvoiceRow).where(InvoiceRow.id.in_(test_ids))).all()
    vendor_ids = sorted({t.vendor_id for t in tests if t.vendor_id is not None})

    # In-scope purchase orders: every PO a test document names, whatever its date.
    po_refs = {(t.vendor_id, normalise_number(t.po_number_read)) for t in tests if t.po_number_read}
    po_ids = {t.purchase_order_id for t in tests if t.purchase_order_id}
    po_rows = [
        p
        for p in s.scalars(select(PurchaseOrderRow).where(PurchaseOrderRow.vendor_id.in_(vendor_ids))).all()
        if p.id in po_ids or (p.vendor_id, p.po_number_norm) in po_refs
    ]
    po_line_rows = s.scalars(
        select(PoLineRow).where(PoLineRow.purchase_order_id.in_([p.id for p in po_rows]))
    ).all()
    po_line_ids = [pl.id for pl in po_line_rows]
    pos = tuple(
        PurchaseOrder(
            id=str(p.id),
            vendor_id=str(p.vendor_id),
            po_number=p.po_number,
            txn_date=p.txn_date,
            lines=tuple(
                PoLine(
                    id=str(pl.id),
                    line_no=pl.line_no or 0,
                    item_id=_s(pl.item_id),
                    qty_ordered=pl.qty_ordered,
                    uom=pl.uom,
                    unit_price=pl.unit_price,
                    qbo_billed_qty=pl.qbo_billed_qty,
                    charge_kind=LineKind(pl.charge_kind) if pl.charge_kind else None,
                    amount=pl.amount,
                )
                for pl in po_line_rows
                if pl.purchase_order_id == p.id
            ),
        )
        for p in po_rows
    )

    # Every uploaded invoice and credit note of these vendors: history has no date limit.
    inv_rows = s.scalars(select(InvoiceRow).where(InvoiceRow.vendor_id.in_(vendor_ids))).all()
    lines = s.scalars(
        select(InvoiceLineRow).where(InvoiceLineRow.invoice_id.in_([i.id for i in inv_rows]))
    ).all()
    doc_states = dict(
        s.execute(
            select(DocumentRow.id, DocumentRow.state).where(
                DocumentRow.id.in_([i.document_id for i in inv_rows])
            )
        ).all()
    )
    docs = tuple(
        Document(
            id=str(i.id),
            doc_type=DocType(i.doc_type),
            vendor_id=str(i.vendor_id),
            doc_number=i.doc_number,
            doc_date=i.doc_date,
            file_sha256=i.file_order_key,
            verification=VerificationStatus(i.verification_status),
            lines=tuple(
                DocLine(
                    id=str(ln.id),
                    line_no=ln.line_no,
                    kind=LineKind(ln.line_kind),
                    supplier_item_code=ln.supplier_item_code,
                    qty=ln.qty,
                    uom=ln.uom,
                    unit_price=ln.unit_price,
                    amount=ln.amount,
                )
                for ln in lines
                if ln.invoice_id == i.id
            ),
            po_number=i.po_number_read,
            currency=i.currency,
            total=i.total,
            references_invoice_number=i.references_invoice_number,
        )
        for i in inv_rows
        if doc_states.get(i.document_id) != "duplicate_file"
    )

    imports = s.scalars(select(ReceivingImportRow)).all()
    receipt_rows = s.execute(
        select(ReceiptLineRow, ReceiptRow)
        .join(
            ReceiptRow,
            (ReceiptRow.id == ReceiptLineRow.receipt_id) & (ReceiptRow.tenant_id == ReceiptLineRow.tenant_id),
        )
        .where(ReceiptLineRow.po_line_id.in_(po_line_ids))
    ).all()
    receipts = tuple(
        ReceiptLine(
            id=str(rl.id),
            import_id=str(rl.receiving_import_id),
            po_line_id=str(rl.po_line_id),
            qty_in_po_uom=rl.qty_in_po_uom,
            received_date=r.received_date,
            receiver_marks_recorded=bool(r.receiver_marks_present and r.receiver_name),
            added_after_exception=rl.added_after_exception,
            late_approved=rl.late_approved,
        )
        for rl, r in receipt_rows
    )
    receiving_imports = tuple(
        ReceivingImport(
            id=str(i.id),
            evidence_class=EvidenceClass(i.evidence_class),
            committed=i.state in {"succeeded", "voided"},
            voided=i.state == "voided",
            declared_complete=i.declared_complete,
            coverage_start=i.coverage_start,
            coverage_end=i.coverage_end,
        )
        for i in imports
    )

    bill_rows = s.scalars(select(QboBillRow).where(QboBillRow.vendor_id.in_(vendor_ids))).all()
    bill_lines = s.scalars(
        select(QboBillLineRow).where(QboBillLineRow.qbo_bill_id.in_([b.id for b in bill_rows]))
    ).all()
    bills = tuple(
        QboBill(
            id=str(b.id),
            txn_type=b.txn_type,
            vendor_id=str(b.vendor_id),
            doc_number=b.doc_number,
            txn_date=b.txn_date,
            total=b.total,
            references_invoice_number=b.references_invoice_number,
            lines=tuple(
                QboBillLine(id=str(bl.id), po_line_id=_s(bl.po_line_id), qty=bl.qty, amount=bl.amount)
                for bl in bill_lines
                if bl.qbo_bill_id == b.id
            ),
        )
        for b in bill_rows
    )

    alias_rows = s.scalars(select(ItemAlias).where(ItemAlias.vendor_id.in_(vendor_ids))).all()
    aliases = tuple(
        Alias(
            id=str(a.id),
            vendor_id=str(a.vendor_id),
            supplier_item_code=a.supplier_item_code,
            item_id=str(a.item_id),
            status=AliasStatus(a.status),
            conversion_factor=a.conversion_factor,
            supplier_uom=a.supplier_uom,
            item_uom=a.item_uom,
            approved=a.approved_by is not None,
        )
        for a in alias_rows
    )

    tol_rows = s.scalars(
        select(ToleranceRule)
        .where(ToleranceRule.valid_to.is_(None))
        .where(or_(ToleranceRule.vendor_id.is_(None), ToleranceRule.vendor_id.in_(vendor_ids)))
    ).all()
    default = Tolerance()
    vendor_tols: list[tuple[str, Tolerance]] = []
    for t in tol_rows:
        tol = Tolerance(
            qty_tolerance=t.qty_tolerance,
            price_tol_abs=t.price_tol_abs,
            price_tol_pct=t.price_tol_pct,
            charge_allowance=t.charge_allowance,
            rule_id=str(t.id),
        )
        if t.vendor_id is None:
            default = tol
        else:
            vendor_tols.append((str(t.vendor_id), tol))

    decided = s.scalars(
        select(ExceptionRow).where(
            ExceptionRow.resolution_code.in_(
                ["confirmed_not_received", "confirmed_duplicate", "not_a_duplicate"]
            )
        )
    ).all()
    confirmed = frozenset(
        str(e.invoice_line_id)
        for e in decided
        if e.type == "receipt_absent" and e.resolution_code == "confirmed_not_received" and e.invoice_line_id
    )
    dup_decisions = tuple(
        (str(e.invoice_id), DuplicateDecision(e.resolution_code))
        for e in decided
        if e.type == "possible_duplicate" and e.resolution_code
    )

    return MatchInput(
        tenant_currency=tenant_currency,
        test_document_ids=frozenset(str(t.id) for t in tests),
        documents=docs,
        purchase_orders=pos,
        aliases=aliases,
        receiving_imports=receiving_imports,
        receipt_lines=receipts,
        qbo_bills=bills,
        default_tolerance=default,
        vendor_tolerances=tuple(vendor_tols),
        duplicate_decisions=dup_decisions,
        confirmed_not_received=confirmed,
        ruleset_code=ruleset_code,
    )
