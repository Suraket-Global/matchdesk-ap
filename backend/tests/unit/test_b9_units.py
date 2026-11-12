"""B9 unit tests: the controller's credit decision in the pure rule engine (MH-09), arrival order."""

from __future__ import annotations

from datetime import date

from matchdesk.matching import (
    CreditDecision,
    CreditDecisionInput,
    ExceptionStatus,
    ExceptionType,
    ResolutionCode,
    ValueClass,
    evaluate,
)

from .builders import D, build, class_a, invoice, qbo_bill, receipt

T = ExceptionType
BASE = {"imports": (class_a(),), "receipts": (receipt("r1", "60", date(2026, 10, 3)),)}
VC = qbo_bill("vc78", "VC-78", date(2026, 10, 25), "", "168.00", txn_type="vendor_credit", po_line=None)


def _over(res):  # type: ignore[no-untyped-def]
    return next(e for e in res.exceptions if e.type == T.QTY_OVER_RECEIVED)


def _decision(inv_id: str, line_id: str, decision: CreditDecision, bill: str = "vc78") -> CreditDecisionInput:
    return CreditDecisionInput(inv_id, line_id, T.QTY_OVER_RECEIVED.value, bill, decision)


def test_credited_decision_nets_with_that_credit_and_is_not_a_finding() -> None:
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    undecided = _over(evaluate(build(docs=(inv,), bills=(VC,), **BASE)))
    assert undecided.value_class == ValueClass.OPEN_UNDECIDED and not undecided.qualifying
    d = _decision("inv1", undecided.line_id or "", CreditDecision.CREDITED)
    e = _over(evaluate(build(docs=(inv,), bills=(VC,), credit_decisions=(d,), **BASE)))
    assert e.status == ExceptionStatus.RESOLVED and e.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
    assert e.qualifying is False and e.related_qbo_bill_ids == ("vc78",)


def test_not_credited_is_a_finding_and_that_credit_never_flags_it_again() -> None:
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    line = _over(evaluate(build(docs=(inv,), bills=(VC,), **BASE))).line_id or ""
    d = _decision("inv1", line, CreditDecision.NOT_CREDITED)
    e = _over(evaluate(build(docs=(inv,), bills=(VC,), credit_decisions=(d,), **BASE)))
    assert e.status == ExceptionStatus.OPEN and e.possibly_credited_bill_id is None
    assert e.value_class == ValueClass.FINDING_CANDIDATE and e.qualifying is True
    assert e.reported_amount == D("168.00")


def test_one_credit_nets_one_exception_whatever_the_document_order() -> None:
    a = invoice("a", "INV-A", date(2026, 10, 4), "100")
    b = invoice("b", "INV-B", date(2026, 10, 5), "40")  # another 168.00 above received
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "100", date(2026, 10, 3)),)}
    first = evaluate(build(docs=(a, b), bills=(VC,), **base))
    flagged = [e for e in first.exceptions if e.possibly_credited_bill_id == "vc78"]
    assert flagged, "the vendor-only credit flags a matching exception"
    target = flagged[0]
    d = CreditDecisionInput(
        target.document_id, target.line_id or "", target.type.value, "vc78", CreditDecision.CREDITED
    )
    for docs in ((a, b), (b, a)):
        res = evaluate(build(docs=docs, bills=(VC,), credit_decisions=(d,), **base))
        netted = [e for e in res.exceptions if e.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT]
        assert len(netted) == 1 and netted[0].key == target.key
        assert not [e for e in res.exceptions if e.possibly_credited_bill_id == "vc78"]


def test_a_credited_decision_that_no_longer_fits_is_not_applied() -> None:
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    line = _over(evaluate(build(docs=(inv,), bills=(VC,), **BASE))).line_id or ""
    d = _decision("inv1", line, CreditDecision.CREDITED)
    small = qbo_bill("vc78", "VC-78", date(2026, 10, 25), "", "50.00", txn_type="vendor_credit", po_line=None)
    e = _over(evaluate(build(docs=(inv,), bills=(small,), credit_decisions=(d,), **BASE)))
    assert e.resolution_code is None and e.qualifying is True  # never netted by a credit that does not fit
