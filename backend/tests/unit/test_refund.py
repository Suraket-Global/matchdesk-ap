"""IT-17 (a), (b), (c), (e) as a calculation over engine output; (d) needs report tables (not built)."""

from __future__ import annotations

from datetime import date

from matchdesk.matching import evaluate
from matchdesk.reporting import calculate_refund

from .builders import D, build, class_a, invoice, receipt


def test_it17a_findings_above_threshold_no_refund():
    res = evaluate(
        build(
            docs=(invoice("i", "INV-1", date(2026, 10, 4), "100", "23.32"),),
            imports=(class_a(),),
            receipts=(receipt("r", "100", date(2026, 10, 3)),),
        )
    )
    calc = calculate_refund(res.exceptions)
    assert calc.qualifying_total == D("1912.00") and calc.refund_due is False


def test_it17b_nothing_found_refund():
    res = evaluate(
        build(
            docs=(invoice("i", "INV-1", date(2026, 10, 4), "100"),),
            imports=(class_a(),),
            receipts=(receipt("r", "100", date(2026, 10, 3)),),
        )
    )
    calc = calculate_refund(res.exceptions)
    assert calc.qualifying_total == D("0.00") and calc.refund_due is True


def test_it17c_no_receiving_evidence_refund_with_unverified_shown():
    res = evaluate(
        build(
            docs=(
                invoice("a", "INV-A", date(2026, 10, 4), "60", "4.35"),
                invoice("b", "INV-B", date(2026, 10, 5), "40"),
            )
        )
    )
    calc = calculate_refund(res.exceptions)
    assert calc.qualifying_total == D("9.00")
    assert calc.unverified_total == D("252.00") + D("168.00")
    assert calc.refund_due is True


def test_it17e_waivers_do_not_remove_qualifying_discrepancies():
    res = evaluate(
        build(
            docs=(invoice("i", "INV-1", date(2026, 10, 4), "100", "23.32"),),
            imports=(class_a(),),
            receipts=(receipt("r", "100", date(2026, 10, 3)),),
        )
    )
    all_lines = frozenset(e.line_id or "" for e in res.exceptions)
    assert calculate_refund(res.exceptions, waived_line_ids=all_lines).refund_due is False
