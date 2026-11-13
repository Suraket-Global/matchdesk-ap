"""Assemble a ``MatchInput`` from the database for a scope of test documents (T-4.1.6 (a)).

No date filter is applied to purchase-order history, receipts, earlier invoices,
bills or credits (CLAUDE.md prohibited shortcuts; AD-13). Rows are read through
the caller's tenant session, so row-level security bounds everything.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from matchdesk.exceptions.models import ExceptionRow, ItemAlias, ToleranceRule
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow, live_invoice
from matchdesk.matching import (
    Alias,
    AliasStatus,
    CreditDecision,
    CreditDecisionInput,
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
    tests = s.scalars(select(InvoiceRow).where(InvoiceRow.id.in_(test_ids), live_invoice())).all()
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
        select(PoLineRow).where(
            PoLineRow.purchase_order_id.in_([p.id for p in po_rows]), PoLineRow.removed_at.is_(None)
        )
    ).all()
    po_line_ids = [pl.id for pl in po_line_rows]
    unknown = unknown_history(s, po_rows)
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
            unknown_history=unknown.get(p.id, ()),
        )
        for p in po_rows
    )

    # Every uploaded invoice and credit note of these vendors: history has no date limit.
    # Test invoices are always loaded, even with no identified vendor, so none can drop out of
    # the result silently (B1-006); the engine turns a vendor-less document into an exception.
    inv_rows = s.scalars(
        select(InvoiceRow).where(
            or_(InvoiceRow.vendor_id.in_(vendor_ids), InvoiceRow.id.in_(test_ids)), live_invoice()
        )
    ).all()
    lines = s.scalars(
        select(InvoiceLineRow).where(
            InvoiceLineRow.invoice_id.in_([i.id for i in inv_rows]), InvoiceLineRow.removed_at.is_(None)
        )
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
            vendor_id=str(i.vendor_id) if i.vendor_id else "",
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
    loose = unattributed_bills(s, vendor_ids, bill_rows, bill_lines)
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
            unattributed_po_ids=loose.get(b.id, ()),
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

    # B9: the controller's credit decisions, keyed like the stored exception (document, line, type).
    credit_rows = s.scalars(
        select(ExceptionRow).where(
            ExceptionRow.credit_decision.is_not(None),
            ExceptionRow.invoice_id.in_([i.id for i in inv_rows]),
        )
    ).all()
    credit_decisions = tuple(
        sorted(
            (
                CreditDecisionInput(
                    document_id=str(e.invoice_id),
                    line_id=str(e.invoice_line_id) if e.invoice_line_id else "",
                    type=e.type,
                    qbo_bill_id=str(e.credit_decision_bill_id),
                    decision=CreditDecision(e.credit_decision),
                )
                for e in credit_rows
                if e.credit_decision_bill_id is not None and e.credit_decision is not None
            ),
            key=lambda d: (d.key, d.qbo_bill_id),
        )
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
        credit_decisions=credit_decisions,
        ruleset_code=ruleset_code,
    )


def unattributed_bills(
    s: Session,
    vendor_ids: Sequence[uuid.UUID],
    bill_rows: Sequence[QboBillRow],
    bill_lines: Sequence[QboBillLineRow],
) -> dict[uuid.UUID, tuple[str, ...]]:
    """B11 (T-1.1.1): for each QuickBooks bill that a PO's own LinkedTxn names and that has an item
    line the sync could not attribute to a single PO line, the ids of the POs naming it."""
    named_by: dict[str, list[str]] = {}
    for po_id, bill_qbo_ids in s.execute(
        select(PurchaseOrderRow.id, PurchaseOrderRow.linked_bill_qbo_ids).where(
            PurchaseOrderRow.vendor_id.in_(vendor_ids)
        )
    ).all():
        for q in bill_qbo_ids or []:
            named_by.setdefault(q, []).append(str(po_id))
    out: dict[uuid.UUID, tuple[str, ...]] = {}
    for b in bill_rows:
        if b.txn_type != "bill" or b.qbo_id not in named_by:
            continue
        if any(bl.qbo_bill_id == b.id and bl.po_line_id is None and bl.qty is not None for bl in bill_lines):
            out[b.id] = tuple(sorted(named_by[b.qbo_id]))
    return out


def unknown_history(s: Session, po_rows: Sequence[PurchaseOrderRow]) -> dict[uuid.UUID, tuple[str, ...]]:
    """B11 (lead review): why each PO's QuickBooks history is unknown, in words. A LinkedTxn entry
    MatchDesk does not read (for example a Purchase), or a bill the PO names that is not stored as a
    QuickBooks bill (skipped for its currency, or not read), each give one reason (S-10 shows them)."""
    named = {q for p in po_rows for q in (p.linked_bill_qbo_ids or [])}
    held = (
        set(
            s.scalars(
                select(QboBillRow.qbo_id).where(QboBillRow.txn_type == "bill", QboBillRow.qbo_id.in_(named))
            )
        )
        if named
        else set()
    )
    out: dict[uuid.UUID, tuple[str, ...]] = {}
    for p in po_rows:
        reasons = [
            f"QuickBooks links this purchase order to {kind} {txn_id}, which MatchDesk does not read"
            for kind, _, txn_id in (t.partition(":") for t in p.unread_linked_txns or [])
        ]
        reasons += [
            f"QuickBooks links this purchase order to bill {b}, which MatchDesk does not hold "
            "(skipped for its currency, or not read)"
            for b in sorted(set(p.linked_bill_qbo_ids or []) - held)
        ]
        if reasons:
            out[p.id] = tuple(reasons)
    return out
