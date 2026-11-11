"""C1 corrections (2026-11-11): UT-32 QuickBooks item-receipt independence, UT-33 three-count measurement."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from matchdesk.matching import ExceptionResult, ExceptionType, ValueClass
from matchdesk.receiving import ItemReceiptRejection, QboItemReceiptRow, item_receipt_rejection
from matchdesk.reporting import measure_findings

T0 = datetime(2026, 10, 3, 9, 0)
T1 = datetime(2026, 10, 6, 14, 0)
AP = frozenset({"Ap Clerk"})


def row(**kw: object) -> QboItemReceiptRow:
    base: dict[str, object] = {
        "po_number": "PO-4471",
        "created_by": "Warehouse Receiver",
        "created_at": T0,
        "linked_bill_created_by": "Ap Clerk",
        "linked_bill_created_at": T1,
    }
    base.update(kw)
    return QboItemReceiptRow(**base)  # type: ignore[arg-type]


def test_ut32a_receiver_entry_before_bill_counts():
    assert item_receipt_rejection(row(), AP) is None
    assert item_receipt_rejection(row(linked_bill_created_by=None, linked_bill_created_at=None), AP) is None


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"created_by": None}, ItemReceiptRejection.CREATOR_UNKNOWN),
        ({"created_by": "  "}, ItemReceiptRejection.CREATOR_UNKNOWN),
        ({"created_at": None}, ItemReceiptRejection.CREATED_AT_UNKNOWN),
        ({"created_by": "ap  CLERK"}, ItemReceiptRejection.ENTERED_BY_AP_STAFF),
        (
            {"created_by": "Office Manager", "linked_bill_created_by": "office manager"},
            ItemReceiptRejection.ENTERED_BY_BILL_ENTERER,
        ),
        ({"created_at": T1}, ItemReceiptRejection.ENTERED_AFTER_BILL),
        ({"created_at": datetime(2026, 10, 7)}, ItemReceiptRejection.ENTERED_AFTER_BILL),
    ],
)
def test_ut32b_item_receipt_not_independent(kw: dict[str, object], reason: ItemReceiptRejection):
    assert item_receipt_rejection(row(**kw), AP) == reason


def exc(doc: str, amount: str) -> ExceptionResult:
    return ExceptionResult(
        type=ExceptionType.PRICE_VARIANCE,
        document_id=doc,
        line_id=f"{doc}-l1",
        value_class=ValueClass.FINDING_CANDIDATE,
        variance_amount=Decimal(amount),
        reported_amount=Decimal(amount),
        qualifying=True,
    )


def test_ut33a_three_counts_kept_separate():
    a, b, c = exc("a", "400.00"), exc("b", "250.00"), exc("c", "90.00")
    not_qualifying = ExceptionResult(
        type=ExceptionType.RECEIPT_ABSENT,
        document_id="d",
        line_id="d-l1",
        value_class=ValueClass.UNVERIFIED,
        variance_amount=None,
        reported_amount=Decimal("700.00"),
        qualifying=False,
    )
    m = measure_findings(
        (a, b, c, not_qualifying),
        confirmed={a.key: Decimal("400.00"), b.key: Decimal("200.00")},
        recovered={a.key: Decimal("150.00")},
    )
    assert (m.flagged.count, m.flagged.amount) == (3, Decimal("740.00"))
    assert (m.controller_confirmed.count, m.controller_confirmed.amount) == (2, Decimal("600.00"))
    assert (m.credit_recovered.count, m.credit_recovered.amount) == (1, Decimal("150.00"))


def test_ut33b_rules_between_counts():
    a, b = exc("a", "400.00"), exc("b", "250.00")
    with pytest.raises(ValueError, match="not a flagged"):
        measure_findings((a,), confirmed={b.key: Decimal("10")}, recovered={})
    with pytest.raises(ValueError, match="exceeds"):
        measure_findings((a,), confirmed={a.key: Decimal("400.01")}, recovered={})
    with pytest.raises(ValueError, match="without a controller-confirmed"):
        measure_findings((a, b), confirmed={a.key: Decimal("1")}, recovered={b.key: Decimal("1")})
    with pytest.raises(ValueError, match="positive"):
        measure_findings((a,), confirmed={a.key: Decimal("0")}, recovered={})
