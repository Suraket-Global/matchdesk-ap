"""B14 (2026-11-17) unit tests for acceptance finding C2: a credit the controller decided clears
exactly the units it covers on a line and raises nothing new from them. Synthetic data."""

from __future__ import annotations

from datetime import date

from matchdesk.matching import (
    CreditDecision,
    CreditDecisionInput,
    ExceptionStatus,
    ExceptionType,
    ResolutionCode,
    evaluate,
)

from .builders import D, build, class_a, invoice, po_4471, qbo_bill, receipt

T = ExceptionType
IMPORTS = (class_a(),)


def _vc(total: str):  # type: ignore[no-untyped-def]
    return qbo_bill("vc9", "VC-DEMO-9", date(2026, 10, 25), "", total, txn_type="vendor_credit", po_line=None)


def _by_type(res, doc: str):  # type: ignore[no-untyped-def]
    return {e.type: e for e in res.exceptions if e.document_id == doc}


def _credited(res, doc: str, typ: ExceptionType) -> CreditDecisionInput:  # type: ignore[no-untyped-def]
    e = _by_type(res, doc)[typ]
    return CreditDecisionInput(doc, e.line_id or "", typ.value, "vc9", CreditDecision.CREDITED)


def test_c2_credit_for_the_larger_amount_closes_the_smaller_on_the_same_units() -> None:
    """Ordered 80, received 60, invoiced 60 then 40: 40 above received (168.00), 20 above ordered
    (84.00, counted under the first). Credited 168.00: 60 remain billed against 80 ordered."""
    kw = {
        "docs": (
            invoice("a", "FF-1002", date(2026, 10, 2), "60"),
            invoice("b", "FF-1003", date(2026, 10, 9), "40"),
        ),
        "po": po_4471(qty_ordered="80"),
        "imports": IMPORTS,
        "receipts": (receipt("r1", "60", date(2026, 9, 28)),),
        "bills": (_vc("168.00"),),
    }
    before = evaluate(build(**kw))
    b = _by_type(before, "b")
    assert b[T.QTY_OVER_RECEIVED].variance_amount == D("168.00")
    assert b[T.QTY_OVER_ORDERED].variance_amount == D("84.00")
    assert b[T.QTY_OVER_ORDERED].reported_amount == D("0.00")  # counted under the other exception
    after = evaluate(build(**kw, credit_decisions=(_credited(before, "b", T.QTY_OVER_RECEIVED),)))
    b = _by_type(after, "b")
    for typ in (T.QTY_OVER_RECEIVED, T.QTY_OVER_ORDERED):
        assert b[typ].status == ExceptionStatus.RESOLVED
        assert b[typ].resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
        assert b[typ].reported_amount == D("0.00") and b[typ].qualifying is False
    assert "the same units" in (b[T.QTY_OVER_ORDERED].label or "")
    assert sum((e.reported_amount for e in after.exceptions), D("0")) == D("0.00")
    assert not [e for e in after.exceptions if e.qualifying]


def test_c2_credit_for_the_smaller_amount_leaves_only_what_it_did_not_cover() -> None:
    """Ordered 60, received 80, invoiced 60 then 40: 20 above received (84.00) and 40 above ordered
    (168.00, the amount reported). A credit of 84.00 decided for the first leaves 84.00 of the
    second, not 168.00 and not nothing."""
    kw = {
        "docs": (
            invoice("a", "FF-1002", date(2026, 10, 2), "60"),
            invoice("b", "FF-1003", date(2026, 10, 9), "40"),
        ),
        "po": po_4471(qty_ordered="60"),
        "imports": IMPORTS,
        "receipts": (receipt("r1", "80", date(2026, 9, 28)),),
        "bills": (_vc("84.00"),),
    }
    before = evaluate(build(**kw))
    b = _by_type(before, "b")
    assert b[T.QTY_OVER_RECEIVED].variance_amount == D("84.00")  # 100 invoiced, 80 received
    assert b[T.QTY_OVER_ORDERED].variance_amount == D("168.00")  # 100 invoiced, 60 ordered
    assert b[T.QTY_OVER_ORDERED].reported_amount == D("168.00")
    after = evaluate(build(**kw, credit_decisions=(_credited(before, "b", T.QTY_OVER_RECEIVED),)))
    b = _by_type(after, "b")
    assert b[T.QTY_OVER_RECEIVED].resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
    rest = b[T.QTY_OVER_ORDERED]
    assert rest.status == ExceptionStatus.OPEN and rest.variance_amount == D("84.00")
    assert rest.reported_amount == D("84.00") and rest.variance_qty == D("20")
    assert "84.00 of the same units taken off" in (rest.label or "")
    # Never more than before the credit, and exactly the credit less.
    total_before = sum((e.reported_amount for e in before.exceptions), D("0"))
    total_after = sum((e.reported_amount for e in after.exceptions), D("0"))
    assert total_before - total_after == D("84.00")


def test_c2_a_decided_credit_never_raises_the_reported_total() -> None:
    """General property over a grid of ordered and received quantities: deciding "credited" on any
    flagged exception never increases what is reported, and reduces it by no more than the credit."""
    for ordered in ("40", "60", "80", "100", "120"):
        for received in ("0", "40", "60", "80", "100"):
            docs = (
                invoice("a", "FF-1002", date(2026, 10, 2), "60"),
                invoice("b", "FF-1003", date(2026, 10, 9), "40"),
            )
            rc = (receipt("r1", received, date(2026, 9, 28)),) if received != "0" else ()
            base = {"docs": docs, "po": po_4471(qty_ordered=ordered), "imports": IMPORTS, "receipts": rc}
            plain = evaluate(build(**base))
            for target in [e for e in plain.exceptions if e.variance_amount and e.variance_amount > 0]:
                credit = _vc(str(target.variance_amount))
                before = evaluate(build(**base, bills=(credit,)))
                flagged = [e for e in before.exceptions if e.possibly_credited_bill_id == "vc9"]
                for f in flagged:
                    d = CreditDecisionInput(
                        f.document_id, f.line_id or "", f.type.value, "vc9", CreditDecision.CREDITED
                    )
                    after = evaluate(build(**base, bills=(credit,), credit_decisions=(d,)))
                    was = sum((e.reported_amount for e in plain.exceptions), D("0"))
                    now = sum((e.reported_amount for e in after.exceptions), D("0"))
                    assert now <= was, (ordered, received, f.type)
                    assert was - now <= (f.variance_amount or D("0")), (ordered, received, f.type)
                    line_now = sum(
                        (e.reported_amount for e in after.exceptions if e.line_id == f.line_id), D("0")
                    )
                    line_was = sum(
                        (e.reported_amount for e in plain.exceptions if e.line_id == f.line_id), D("0")
                    )
                    assert line_now <= line_was, (ordered, received, f.type)
