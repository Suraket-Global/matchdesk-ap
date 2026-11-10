"""Synthetic golden-fixture builders (execution-plan section 7). Every value is invented.

Vendor "Fictional Supplier T"; PO 4471 line 2: 100 EA at 4.20.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date
from decimal import Decimal as D

from matchdesk.matching import (
    Alias,
    AliasStatus,
    DocLine,
    DocType,
    Document,
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
)

VENDOR = "vendor-T"
ITEM = "item-widget"
PO_DATE = date(2026, 9, 1)


def sha(name: str) -> bytes:
    return hashlib.sha256(name.encode()).digest()


def po_4471(
    qty_ordered: str = "100",
    price: str = "4.20",
    qbo_billed: str | None = None,
    extra_lines: tuple[PoLine, ...] = (),
) -> PurchaseOrder:
    return PurchaseOrder(
        id="po-4471",
        vendor_id=VENDOR,
        po_number="4471",
        txn_date=PO_DATE,
        lines=(
            PoLine(
                id="pol-2",
                line_no=2,
                item_id=ITEM,
                qty_ordered=D(qty_ordered),
                uom="EA",
                unit_price=D(price),
                qbo_billed_qty=D(qbo_billed) if qbo_billed else None,
            ),
            *extra_lines,
        ),
    )


def alias(
    conversion: str = "1",
    approved: bool = True,
    status: AliasStatus = AliasStatus.ACTIVE,
    supplier_uom: str | None = None,
    item_uom: str | None = None,
) -> Alias:
    return Alias(
        id="alias-w",
        vendor_id=VENDOR,
        supplier_item_code="W-100",
        item_id=ITEM,
        status=status,
        conversion_factor=D(conversion),
        supplier_uom=supplier_uom,
        item_uom=item_uom,
        approved=approved,
    )


def invoice(
    doc_id: str,
    number: str,
    day: date,
    qty: str,
    price: str = "4.20",
    *,
    uom: str | None = "EA",
    po: str = "4471",
    code: str = "W-100",
    extra: tuple[DocLine, ...] = (),
    file: str | None = None,
    total: str | None = None,
    currency: str | None = "CAD",
    verification: VerificationStatus = VerificationStatus.PASSED,
) -> Document:
    amount = (D(qty) * D(price)).quantize(D("0.01"))
    lines = (
        DocLine(
            id=f"{doc_id}-l1",
            line_no=1,
            kind=LineKind.ITEM,
            supplier_item_code=code,
            qty=D(qty),
            uom=uom,
            unit_price=D(price),
            amount=amount,
        ),
        *extra,
    )
    tot = D(total) if total else amount + sum((ln.amount or D(0) for ln in extra), D(0))
    return Document(
        id=doc_id,
        doc_type=DocType.INVOICE,
        vendor_id=VENDOR,
        doc_number=number,
        doc_date=day,
        file_sha256=sha(file or doc_id),
        verification=verification,
        lines=lines,
        po_number=po,
        currency=currency,
        total=tot,
    )


def credit_note(
    doc_id: str,
    number: str,
    day: date,
    *,
    qty: str | None,
    amount: str,
    references: str | None,
    po: str | None = None,
    code: str = "W-100",
) -> Document:
    return Document(
        id=doc_id,
        doc_type=DocType.CREDIT_NOTE,
        vendor_id=VENDOR,
        doc_number=number,
        doc_date=day,
        file_sha256=sha(doc_id),
        verification=VerificationStatus.PASSED,
        lines=(
            DocLine(
                id=f"{doc_id}-l1",
                line_no=1,
                kind=LineKind.ITEM,
                supplier_item_code=code if qty else None,
                qty=D(qty) if qty else None,
                uom="EA" if qty else None,
                unit_price=None,
                amount=D(amount),
            ),
        ),
        po_number=po,
        currency="CAD",
        total=D(amount),
        references_invoice_number=references,
    )


def class_a(
    import_id: str = "imp-a", start: date | None = None, end: date | None = None, complete: bool = False
) -> ReceivingImport:
    return ReceivingImport(
        id=import_id,
        evidence_class=EvidenceClass.A,
        committed=True,
        declared_complete=complete,
        coverage_start=start,
        coverage_end=end,
    )


def receipt(
    rid: str, qty: str, day: date, import_id: str = "imp-a", po_line: str = "pol-2", marks: bool = False
) -> ReceiptLine:
    return ReceiptLine(
        id=rid,
        import_id=import_id,
        po_line_id=po_line,
        qty_in_po_uom=D(qty),
        received_date=day,
        receiver_marks_recorded=marks,
    )


def qbo_bill(
    bill_id: str,
    number: str,
    day: date,
    qty: str,
    amount: str,
    txn_type: str = "bill",
    po_line: str | None = "pol-2",
    references: str | None = None,
) -> QboBill:
    return QboBill(
        id=bill_id,
        txn_type=txn_type,
        vendor_id=VENDOR,
        doc_number=number,
        txn_date=day,
        total=D(amount),
        lines=(
            QboBillLine(
                id=f"{bill_id}-l1", po_line_id=po_line, qty=D(qty) if qty else None, amount=D(amount)
            ),
        )
        if po_line
        else (),
        references_invoice_number=references,
    )


def build(
    *,
    docs: tuple[Document, ...],
    tests: tuple[str, ...] | None = None,
    po: PurchaseOrder | None = None,
    aliases: tuple[Alias, ...] | None = None,
    imports: tuple[ReceivingImport, ...] = (),
    receipts: tuple[ReceiptLine, ...] = (),
    bills: tuple[QboBill, ...] = (),
    tolerance: Tolerance | None = None,
    **kw: object,
) -> MatchInput:
    return MatchInput(
        tenant_currency="CAD",
        test_document_ids=frozenset(tests if tests is not None else [d.id for d in docs]),
        documents=docs,
        purchase_orders=(po or po_4471(),),
        aliases=aliases if aliases is not None else (alias(),),
        receiving_imports=imports,
        receipt_lines=receipts,
        qbo_bills=bills,
        default_tolerance=tolerance or Tolerance(),
        **kw,  # type: ignore[arg-type]
    )


MAX_TOLERANCE = Tolerance(
    qty_tolerance=D("9999999999.9999"),
    price_tol_abs=D("99999999.999999"),
    price_tol_pct=D("10"),
    charge_allowance=D("999999999999.99"),
)

__all__ = ["D", "replace"]
