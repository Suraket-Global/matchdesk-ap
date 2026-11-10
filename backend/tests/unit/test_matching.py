"""Golden-fixture unit tests for rule set v1 (execution-plan section 7.1).

Each test name starts with its catalogue ID. Fixtures are synthetic.
"""

from __future__ import annotations

from datetime import date

from matchdesk.matching import (
    QBO_CREDIT_LABEL,
    AliasStatus,
    DocLine,
    DuplicateDecision,
    EvidenceClass,
    ExceptionStatus,
    ExceptionType,
    LineKind,
    LineStatus,
    ReceivingImport,
    ResolutionCode,
    SubReason,
    Tolerance,
    ValueClass,
    VerificationStatus,
    evaluate,
    normalise_number,
)

from .builders import (
    MAX_TOLERANCE,
    VENDOR,
    D,
    alias,
    build,
    class_a,
    credit_note,
    invoice,
    po_4471,
    qbo_bill,
    receipt,
)

T = ExceptionType


def types(result, line_id=None, document_id=None, open_only=False):
    return sorted(
        e.type.value
        for e in result.exceptions_for(line_id=line_id, document_id=document_id)
        if not open_only or e.status == ExceptionStatus.OPEN
    )


def one(result, typ, line_id=None, document_id=None):
    found = [e for e in result.exceptions_for(line_id=line_id, document_id=document_id) if e.type == typ]
    assert len(found) == 1, found
    return found[0]


def test_ut01_partial_deliveries_pass_cumulatively():
    inp = build(
        docs=(
            invoice("inv1", "INV-01042", date(2026, 10, 4), "60"),
            invoice("inv2", "INV-01077", date(2026, 10, 18), "40"),
        ),
        imports=(class_a(),),
        receipts=(receipt("r1", "60", date(2026, 10, 3)), receipt("r2", "40", date(2026, 10, 17))),
    )
    res = evaluate(inp)
    assert res.line("inv1-l1").status == LineStatus.MATCHED
    assert res.line("inv2-l1").status == LineStatus.MATCHED
    assert res.line("inv1-l1").qty_invoiced_cum_net == D("60")
    assert res.line("inv2-l1").qty_invoiced_cum_net == D("100")
    assert res.exceptions == ()


def test_ut02_over_invoicing_against_received():
    inp = build(
        docs=(invoice("inv1", "INV-01042", date(2026, 10, 4), "100"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "60", date(2026, 10, 3)),),
    )
    res = evaluate(inp)
    e = one(res, T.QTY_OVER_RECEIVED)
    assert e.variance_qty == D("40")
    assert e.variance_amount == D("168.00")
    assert e.qualifying is True
    assert res.line("inv1-l1").status == LineStatus.EXCEPTION


def test_ut03_no_receipt_is_receipt_absent_under_maximum_tolerances():
    for tol in (Tolerance(), MAX_TOLERANCE):
        res = evaluate(build(docs=(invoice("inv1", "INV-01042", date(2026, 10, 4), "100"),), tolerance=tol))
        line = res.line("inv1-l1")
        assert line.status == LineStatus.EXCEPTION
        assert line.receipt_line_count == 0
        e = one(res, T.RECEIPT_ABSENT)
        assert e.value_class == ValueClass.UNVERIFIED
        assert e.reported_amount == D("420.00")
        assert e.sub_reason == SubReason.NO_EVIDENCE
        assert e.qualifying is False


def test_ut04_price_tolerance():
    inp = build(
        docs=(
            invoice("a", "INV-A", date(2026, 10, 4), "60", "4.21"),
            invoice("b", "INV-B", date(2026, 10, 5), "60", "4.35"),
        ),
        po=po_4471(qty_ordered="200"),
        imports=(class_a(),),
        receipts=(receipt("r1", "120", date(2026, 10, 3)),),
    )
    res = evaluate(inp)
    assert res.line("a-l1").status == LineStatus.MATCHED
    e = one(res, T.PRICE_VARIANCE, document_id="b")
    assert e.variance_amount == D("9.00")


def test_ut05_duplicate_and_possible_duplicate():
    assert normalise_number("INV-01042") == normalise_number("inv 1042") == "INV1042"
    inp = build(
        docs=(
            invoice("d1", "INV-01042", date(2026, 10, 4), "10"),
            invoice("d2", "inv 1042", date(2026, 10, 6), "10"),
            invoice("p1", "INV-2001", date(2026, 10, 10), "10", total="1284.50"),
            invoice("p2", "INV-2001A", date(2026, 10, 15), "10", total="1284.50"),
        ),
        imports=(class_a(),),
        receipts=(receipt("r1", "100", date(2026, 10, 1)),),
    )
    res = evaluate(inp)
    assert types(res, document_id="d1") == []
    dup = one(res, T.DUPLICATE, document_id="d2")
    assert dup.related_document_id == "d1"
    pdup = one(res, T.POSSIBLE_DUPLICATE, document_id="p2")
    assert pdup.value_class == ValueClass.OPEN_UNDECIDED and pdup.qualifying is False
    assert res.line("p2-l1").status == LineStatus.MATCHED  # its lines are still matched


def test_ut06_credit_note_clears_over_received():
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "60", date(2026, 10, 3)),)}
    before = evaluate(build(docs=(inv,), **base))
    assert one(before, T.QTY_OVER_RECEIVED).variance_amount == D("168.00")
    cn = credit_note("cn31", "CN-0031", date(2026, 10, 20), qty="40", amount="168.00", references="INV-01042")
    after = evaluate(build(docs=(inv, cn), **base))
    e = one(after, T.QTY_OVER_RECEIVED, document_id="inv1")
    assert e.status == ExceptionStatus.RESOLVED
    assert e.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
    assert e.related_document_id == "cn31"
    assert e.reported_amount == D("0.00") and e.qualifying is False
    assert after.line("inv1-l1").qty_invoiced_cum_net == D("60")
    assert after.line("inv1-l1").status == LineStatus.MATCHED
    assert after.line("cn31-l1").status == LineStatus.NOT_EVALUATED  # linked, not matched


def test_ut07_unit_conversion_through_approved_alias():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 4), "5", "50.40", uom="CS"),),
        aliases=(alias("12", approved=True, supplier_uom="CS", item_uom="EA"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "60", date(2026, 10, 3)),),
    )
    line = evaluate(inp).line("inv1-l1")
    assert line.status == LineStatus.MATCHED
    assert line.qty_invoiced_cum_net == D("60")
    assert line.invoice_unit_price_po_uom == D("4.200000")


def test_ut07b_unapproved_conversion_does_not_pass():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 4), "5", "50.40", uom="CS"),),
        aliases=(alias("12", approved=False, supplier_uom="CS", item_uom="EA"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "60", date(2026, 10, 3)),),
    )
    res = evaluate(inp)
    assert types(res) == ["alias_unconfirmed"]
    assert res.line("inv1-l1").status == LineStatus.EXCEPTION


def test_ut10_over_ordered():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 4), "110"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "110", date(2026, 10, 3)),),
    )
    res = evaluate(inp)
    assert types(res) == ["qty_over_ordered"]
    e = one(res, T.QTY_OVER_ORDERED)
    assert (e.variance_qty, e.variance_amount) == (D("10"), D("42.00"))


def test_ut12_september_qbo_bill_counts_as_invoiced():
    inp = build(
        docs=(invoice("oct", "INV-01042", date(2026, 10, 8), "100"),),
        po=po_4471(qbo_billed="100"),
        bills=(qbo_bill("qb980", "INV-00980", date(2026, 9, 15), "100", "420.00"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "100", date(2026, 10, 6)),),
    )
    res = evaluate(inp)
    line = res.line("oct-l1")
    assert line.status == LineStatus.EXCEPTION
    assert line.qty_invoiced_cum_net == D("200")
    assert line.qty_invoiced_prior_qbo == D("100")
    e = one(res, T.QTY_OVER_RECEIVED)
    assert (e.variance_qty, e.variance_amount, e.reported_amount) == (D("100"), D("420.00"), D("420.00"))
    # Ordered is also exceeded by the same 100; only one amount is reported for the line.
    assert one(res, T.QTY_OVER_ORDERED).reported_amount == D("0.00")
    assert sum(x.reported_amount for x in res.exceptions) == D("420.00")


def test_ut13_receipt_before_test_month_counts():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 2), "100"),),
        imports=(class_a(),),
        receipts=(receipt("r1", "100", date(2026, 9, 29)),),
    )
    res = evaluate(inp)
    assert res.line("inv1-l1").status == LineStatus.MATCHED
    assert res.exceptions == ()


def test_ut15_history_incomplete_blocks_pass_until_earlier_invoice_supplied():
    base = {
        "po": po_4471(qbo_billed="100"),
        "imports": (class_a(),),
        "receipts": (receipt("r1", "100", date(2026, 9, 20)),),
    }
    oct_inv = invoice("oct", "INV-2", date(2026, 10, 5), "40")
    res = evaluate(build(docs=(oct_inv,), **base))
    assert "history_incomplete" in types(res)
    assert res.line("oct-l1").status == LineStatus.EXCEPTION
    sep_inv = invoice("sep", "INV-1", date(2026, 9, 21), "60")
    res2 = evaluate(build(docs=(sep_inv, oct_inv), tests=("oct",), **base))
    assert res2.line("oct-l1").status == LineStatus.MATCHED
    assert res2.exceptions == ()


def _po_three_lines():
    from matchdesk.matching import PoLine

    return po_4471(
        extra_lines=(
            PoLine(
                id="pol-1", line_no=1, item_id="item-a", qty_ordered=D("5"), uom="EA", unit_price=D("1.00")
            ),
            PoLine(
                id="pol-3", line_no=3, item_id="item-c", qty_ordered=D("5"), uom="EA", unit_price=D("1.00")
            ),
        )
    )


def test_ut16_not_received_where_log_covers_the_order():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 4), "100"),),
        po=_po_three_lines(),
        imports=(class_a(start=date(2026, 9, 1), end=date(2026, 10, 31), complete=True),),
        receipts=(
            receipt("r1", "5", date(2026, 9, 10), po_line="pol-1"),
            receipt("r3", "5", date(2026, 9, 10), po_line="pol-3"),
        ),
    )
    res = evaluate(inp)
    e = one(res, T.RECEIPT_ABSENT)
    assert e.sub_reason == SubReason.NOT_RECEIVED
    assert e.value_class == ValueClass.FINDING_CANDIDATE
    assert e.reported_amount == D("420.00")
    assert e.qualifying is True
    assert res.line("inv1-l1").covered is True


def test_ut16b_log_not_reaching_14_days_after_invoice_is_unverified():
    inp = build(
        docs=(invoice("inv1", "INV-1", date(2026, 10, 20), "100"),),
        po=_po_three_lines(),
        imports=(class_a(start=date(2026, 9, 1), end=date(2026, 10, 31), complete=True),),
    )
    e = one(evaluate(inp), T.RECEIPT_ABSENT)
    assert e.sub_reason == SubReason.NO_EVIDENCE and e.qualifying is False


def test_ut17_no_receiving_import_then_controller_confirms():
    inv = invoice("inv1", "INV-1", date(2026, 10, 4), "100")
    res = evaluate(build(docs=(inv,), po=_po_three_lines()))
    e = one(res, T.RECEIPT_ABSENT)
    assert (e.sub_reason, e.value_class, e.qualifying) == (
        SubReason.NO_EVIDENCE,
        ValueClass.UNVERIFIED,
        False,
    )
    res2 = evaluate(build(docs=(inv,), po=_po_three_lines(), confirmed_not_received=frozenset({"inv1-l1"})))
    e2 = one(res2, T.RECEIPT_ABSENT)
    assert e2.value_class == ValueClass.FINDING_CANDIDATE and e2.qualifying is True
    assert e2.resolution_code == ResolutionCode.CONFIRMED_NOT_RECEIVED
    assert e2.reported_amount == D("420.00")
    assert res2.line("inv1-l1").status == LineStatus.EXCEPTION  # still never matched


def test_ut18_qbo_vendor_credits():
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "60", date(2026, 10, 3)),)}
    vc_line = qbo_bill("vc77", "VC-77", date(2026, 10, 25), "40", "168.00", txn_type="vendor_credit")
    a = evaluate(build(docs=(inv,), bills=(vc_line,), **base))
    ea = one(a, T.QTY_OVER_RECEIVED)
    assert ea.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
    assert ea.label == QBO_CREDIT_LABEL
    vc_amount = qbo_bill(
        "vc78", "VC-78", date(2026, 10, 25), "", "168.00", txn_type="vendor_credit", po_line=None
    )
    b = evaluate(build(docs=(inv,), bills=(vc_amount,), **base))
    eb = one(b, T.QTY_OVER_RECEIVED)
    assert eb.status == ExceptionStatus.OPEN
    assert eb.possibly_credited_bill_id == "vc78"
    assert eb.value_class == ValueClass.OPEN_UNDECIDED and eb.qualifying is False


def test_ut19_price_only_credit():
    inv = invoice("b", "INV-B", date(2026, 10, 5), "60", "4.35")
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "60", date(2026, 10, 3)),)}
    full = evaluate(
        build(
            docs=(
                inv,
                credit_note(
                    "cn40", "CN-0040", date(2026, 10, 9), qty=None, amount="9.00", references="INV-B"
                ),
            ),
            **base,
        )
    )
    e = one(full, T.PRICE_VARIANCE, document_id="b")
    assert e.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT and e.reported_amount == D("0.00")
    part = evaluate(
        build(
            docs=(
                inv,
                credit_note(
                    "cn41", "CN-0041", date(2026, 10, 9), qty=None, amount="5.00", references="INV-B"
                ),
            ),
            **base,
        )
    )
    e2 = one(part, T.PRICE_VARIANCE, document_id="b")
    assert e2.status == ExceptionStatus.OPEN and e2.variance_amount == D("4.00")


def test_ut20_credit_after_test_month_is_netted():
    inv = invoice("inv1", "INV-01042", date(2026, 10, 4), "100")
    cn = credit_note("cn31", "CN-0031", date(2026, 11, 12), qty="40", amount="168.00", references="INV-01042")
    res = evaluate(
        build(
            docs=(inv, cn),
            tests=("inv1",),
            imports=(class_a(),),
            receipts=(receipt("r1", "60", date(2026, 10, 3)),),
        )
    )
    assert types(res, open_only=True) == []


def test_ut21_return_without_and_with_credit():
    inv = invoice("inv1", "INV-1", date(2026, 10, 4), "100")
    base = {
        "imports": (class_a(),),
        "receipts": (receipt("r1", "100", date(2026, 10, 1)), receipt("r2", "-10", date(2026, 10, 10))),
    }
    a = evaluate(build(docs=(inv,), **base))
    e = one(a, T.QTY_OVER_RECEIVED)
    assert (e.variance_amount, e.sub_reason) == (D("42.00"), SubReason.RETURNED_NO_CREDIT)
    cn = credit_note("cn", "CN-1", date(2026, 10, 12), qty="10", amount="42.00", references="INV-1")
    b = evaluate(build(docs=(inv, cn), **base))
    assert b.line("inv1-l1").status == LineStatus.MATCHED


def test_ut22_duplicate_reported_once_under_both_orders():
    d1 = invoice("x1", "INV-01042", date(2026, 10, 4), "100", file="file-one")
    d2 = invoice("x2", "inv 1042", date(2026, 10, 4), "100", file="file-two")
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "100", date(2026, 10, 3)),)}
    r1 = evaluate(build(docs=(d1, d2), **base))
    r2 = evaluate(build(docs=(d2, d1), **base))
    assert r1 == r2
    later = max((d1, d2), key=lambda d: d.file_sha256)
    earlier = min((d1, d2), key=lambda d: d.file_sha256)
    dup = one(r1, T.DUPLICATE)
    assert dup.document_id == later.id and dup.reported_amount == D("420.00")
    assert r1.line(f"{later.id}-l1").status == LineStatus.NOT_EVALUATED
    assert r1.line(f"{earlier.id}-l1").status == LineStatus.MATCHED
    assert [e.type for e in r1.exceptions] == [T.DUPLICATE]
    assert sum(e.reported_amount for e in r1.exceptions if e.qualifying) == D("420.00")


def test_ut22b_confirmed_possible_duplicate_becomes_duplicate():
    inp = build(
        docs=(
            invoice("p1", "INV-2001", date(2026, 10, 10), "10", total="1284.50"),
            invoice("p2", "INV-2001A", date(2026, 10, 15), "10", total="1284.50"),
        ),
        imports=(class_a(),),
        receipts=(receipt("r1", "100", date(2026, 10, 1)),),
        duplicate_decisions=(("p2", DuplicateDecision.CONFIRMED_DUPLICATE),),
    )
    res = evaluate(inp)
    assert types(res, document_id="p2") == ["duplicate"]


def test_ut22c_number_equal_to_two_qbo_bills_is_duplicate():
    inv = invoice("inv1", "INV-555", date(2026, 10, 4), "10")
    bills = (
        qbo_bill("b1", "INV-555", date(2026, 10, 5), "10", "42.00"),
        qbo_bill("b2", "INV555", date(2026, 10, 6), "10", "42.00"),
    )
    res = evaluate(build(docs=(inv,), bills=bills))
    e = one(res, T.DUPLICATE)
    assert e.related_qbo_bill_ids == ("b1", "b2")


def test_ut23_qbo_quantity_is_never_received():
    inp = build(
        docs=(invoice("inv1", "INV-01042", date(2026, 10, 8), "100"),),
        po=po_4471(qbo_billed="100"),
        bills=(qbo_bill("qb1", "INV-01042", date(2026, 10, 9), "100", "420.00"),),
    )
    res = evaluate(inp)
    line = res.line("inv1-l1")
    assert line.receipt_line_count == 0 and line.qty_received_cum == D("0")
    assert line.status == LineStatus.EXCEPTION
    assert "receipt_absent" in types(res)


def test_ut24_ut25_ut26_stopping_checks():
    res = evaluate(build(docs=(invoice("i24", "INV-24", date(2026, 10, 4), "1", po="9999"),)))
    assert types(res) == ["no_po"] and one(res, T.NO_PO).value_class == ValueClass.UNVERIFIED
    other = alias()
    other = type(other)(**{**other.__dict__, "item_id": "item-not-on-po"})
    res = evaluate(build(docs=(invoice("i25", "INV-25", date(2026, 10, 4), "1"),), aliases=(other,)))
    assert types(res) == ["po_line_not_found"]
    res = evaluate(
        build(
            docs=(invoice("i26", "INV-26", date(2026, 10, 4), "1", uom="KG"),),
            aliases=(alias(supplier_uom="CS", item_uom="EA", conversion="12"),),
        )
    )
    assert types(res) == ["uom_unresolved"]
    res = evaluate(
        build(
            docs=(invoice("i4", "INV-4", date(2026, 10, 4), "1"),),
            aliases=(alias(status=AliasStatus.PENDING_APPROVAL),),
        )
    )
    assert types(res) == ["alias_unconfirmed"]


def test_ut27_charge_lines():
    freight = DocLine(id="f-l2", line_no=2, kind=LineKind.FREIGHT, amount=D("85.00"))
    inv = invoice("f", "INV-F", date(2026, 10, 4), "10", extra=(freight,))
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "10", date(2026, 10, 3)),)}
    a = evaluate(build(docs=(inv,), **base))
    e = one(a, T.UNMATCHED_CHARGE)
    assert e.variance_amount == D("85.00") and e.qualifying is True
    b = evaluate(build(docs=(inv,), tolerance=Tolerance(charge_allowance=D("100.00")), **base))
    assert b.line("f-l2").status == LineStatus.CHARGE_OK
    assert types(b) == []


def test_ut28_unlinked_credit():
    cn = credit_note("cnx", "CN-9", date(2026, 10, 9), qty="5", amount="21.00", references=None)
    res = evaluate(build(docs=(cn,)))
    e = one(res, T.CREDIT_UNLINKED)
    assert e.value_class == ValueClass.NONE and e.reported_amount == D("0.00")
    assert types(res) == ["credit_unlinked"]


def test_ut29_currency_unsupported():
    res = evaluate(build(docs=(invoice("usd", "INV-U", date(2026, 10, 4), "1", currency="USD"),)))
    assert types(res) == ["currency_unsupported"]
    assert res.line("usd-l1").status == LineStatus.NOT_EVALUATED


def test_ut30_evidence_classes():
    inv = invoice("inv1", "INV-1", date(2026, 10, 4), "100")
    c = ReceivingImport(id="imp-c", evidence_class=EvidenceClass.C, committed=True)
    b = ReceivingImport(id="imp-b", evidence_class=EvidenceClass.B, committed=True)
    ra = evaluate(
        build(
            docs=(inv,), imports=(c,), receipts=(receipt("rc", "100", date(2026, 10, 3), import_id="imp-c"),)
        )
    )
    assert one(ra, T.RECEIPT_ABSENT).sub_reason == SubReason.SUPPLIER_SLIP_ONLY
    rb = evaluate(
        build(
            docs=(inv,), imports=(b,), receipts=(receipt("rb", "100", date(2026, 10, 3), import_id="imp-b"),)
        )
    )
    assert "receipt_absent" in types(rb)
    assert rb.line("inv1-l1").status == LineStatus.EXCEPTION
    rc = evaluate(
        build(
            docs=(inv,),
            imports=(b,),
            receipts=(receipt("rb", "100", date(2026, 10, 3), import_id="imp-b", marks=True),),
        )
    )
    assert rc.line("inv1-l1").status == LineStatus.MATCHED


def test_ut30b_voided_uncommitted_and_unapproved_late_lines_do_not_count():
    inv = invoice("inv1", "INV-1", date(2026, 10, 4), "100")
    voided = ReceivingImport(id="imp-v", evidence_class=EvidenceClass.A, committed=True, voided=True)
    draft = ReceivingImport(id="imp-d", evidence_class=EvidenceClass.A, committed=False)
    late = receipt("rl", "100", date(2026, 10, 3))
    late = type(late)(**{**late.__dict__, "added_after_exception": True})
    for imports, receipts in (
        ((voided,), (receipt("r", "100", date(2026, 10, 3), import_id="imp-v"),)),
        ((draft,), (receipt("r", "100", date(2026, 10, 3), import_id="imp-d"),)),
        ((class_a(),), (late,)),
        ((), (receipt("r", "100", date(2026, 10, 3), import_id="missing"),)),
    ):
        res = evaluate(build(docs=(inv,), imports=imports, receipts=receipts))
        assert "receipt_absent" in types(res), imports
        assert res.line("inv1-l1").status != LineStatus.MATCHED


def test_ut31_receipt_absent_does_not_stop_price_and_ordered_checks():
    # (a) price variance on a line with no receiving evidence
    a = evaluate(build(docs=(invoice("a", "INV-A", date(2026, 10, 4), "60", "4.35"),)))
    line = a.line("a-l1")
    assert line.status == LineStatus.EXCEPTION
    assert "9" in line.checks_run and "10" in line.checks_run and "8" not in line.checks_run
    assert types(a) == ["price_variance", "receipt_absent"]
    pv, ra = one(a, T.PRICE_VARIANCE), one(a, T.RECEIPT_ABSENT)
    assert (pv.reported_amount, ra.reported_amount) == (D("9.00"), D("252.00"))
    assert pv.reported_amount + ra.reported_amount == D("261.00")
    # (b) over ordered
    b = evaluate(build(docs=(invoice("b", "INV-B", date(2026, 10, 4), "110"),)))
    assert types(b) == ["qty_over_ordered", "receipt_absent"]
    qo, rb = one(b, T.QTY_OVER_ORDERED), one(b, T.RECEIPT_ABSENT)
    assert (qo.reported_amount, rb.reported_amount) == (D("42.00"), D("420.00"))
    # (c) covered: not received is the finding; price variance listed at 0.00
    c = evaluate(
        build(
            docs=(invoice("c", "INV-C", date(2026, 10, 4), "60", "4.35"),),
            imports=(class_a(start=date(2026, 9, 1), end=date(2026, 10, 31), complete=True),),
        )
    )
    rc, pc = one(c, T.RECEIPT_ABSENT), one(c, T.PRICE_VARIANCE)
    assert rc.sub_reason == SubReason.NOT_RECEIVED and rc.reported_amount == D("261.00")
    assert pc.reported_amount == D("0.00") and pc.variance_amount == D("9.00")
    # (d) history incomplete as well: line amount still counted once
    d = evaluate(
        build(docs=(invoice("d", "INV-D", date(2026, 10, 4), "60", "4.35"),), po=po_4471(qbo_billed="100"))
    )
    assert types(d) == ["history_incomplete", "price_variance", "receipt_absent"]
    finding = sum(e.reported_amount for e in d.exceptions if e.value_class == ValueClass.FINDING_CANDIDATE)
    unverified = sum(e.reported_amount for e in d.exceptions if e.value_class == ValueClass.UNVERIFIED)
    assert (finding, unverified) == (D("9.00"), D("252.00"))
    for res in (a, b, c, d):
        assert all(lr.status != LineStatus.MATCHED for lr in res.lines)


def test_both_over_received_and_over_ordered_report_the_larger_once():
    res = evaluate(
        build(
            docs=(invoice("i", "INV-1", date(2026, 10, 4), "120"),),
            imports=(class_a(),),
            receipts=(receipt("r", "90", date(2026, 10, 3)),),
        )
    )
    qr, qo = one(res, T.QTY_OVER_RECEIVED), one(res, T.QTY_OVER_ORDERED)
    assert (qr.variance_qty, qo.variance_qty) == (D("30"), D("20"))
    assert qr.reported_amount == D("126.00") and qo.reported_amount == D("0.00")


def test_extraction_unverified_stops_and_is_excluded():
    res = evaluate(
        build(docs=(invoice("u", "INV-U", date(2026, 10, 4), "1", verification=VerificationStatus.FAILED),))
    )
    assert types(res) == ["extraction_unverified"]
    assert res.line("u-l1").status == LineStatus.NOT_EVALUATED


def test_matched_requires_receipt_for_every_vendor_tolerance():
    vt = ((VENDOR, MAX_TOLERANCE),)
    res = evaluate(build(docs=(invoice("i", "INV-1", date(2026, 10, 4), "1"),), vendor_tolerances=vt))
    assert res.line("i-l1").status == LineStatus.EXCEPTION
