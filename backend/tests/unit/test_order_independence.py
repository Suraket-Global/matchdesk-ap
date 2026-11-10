"""PT-01: arrival order never changes the result (MH-06, R-01)."""

from __future__ import annotations

import itertools
from datetime import date, timedelta

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from matchdesk.matching import evaluate, input_fingerprint

from .builders import D, build, class_a, credit_note, invoice, po_4471, qbo_bill, receipt

DAY0 = date(2026, 8, 20)  # before a September/October test month


@st.composite
def scenarios(draw):
    n_inv = draw(st.integers(1, 4))
    docs = []
    numbers = ["INV-100", "INV-101", "INV-102", "inv 0100"]  # last one duplicates the first
    for i in range(n_inv):
        docs.append(
            invoice(
                f"inv{i}",
                draw(st.sampled_from(numbers)),
                DAY0 + timedelta(days=draw(st.integers(0, 60))),
                str(draw(st.integers(1, 80))),
                draw(st.sampled_from(["4.20", "4.21", "4.35", "4.00"])),
                file=f"file-{i}",
            )
        )
    if draw(st.booleans()):
        docs.append(
            credit_note(
                "cn0",
                "CN-1",
                DAY0 + timedelta(days=draw(st.integers(0, 90))),
                qty=str(draw(st.integers(1, 30))),
                amount="10.00",
                references=draw(st.sampled_from(numbers)),
            )
        )
    receipts = [
        receipt(
            f"r{i}",
            str(draw(st.integers(-10, 80))) if i else str(draw(st.integers(1, 80))),
            DAY0 + timedelta(days=draw(st.integers(0, 60))),
        )
        for i in range(draw(st.integers(0, 3)))
    ]
    receipts = [r for r in receipts if r.qty_in_po_uom != 0]
    bills = []
    if draw(st.booleans()):
        bills.append(
            qbo_bill("qb1", "INV-090", DAY0 - timedelta(days=5), str(draw(st.integers(1, 50))), "50.00")
        )
    if draw(st.booleans()):
        bills.append(
            qbo_bill(
                "vc1", "VC-1", DAY0 + timedelta(days=70), "", "42.00", txn_type="vendor_credit", po_line=None
            )
        )
    billed = draw(st.sampled_from([None, "50", "300"]))
    return docs, receipts, bills, billed


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(scenarios(), st.randoms(use_true_random=False))
def test_pt01_permutations_give_identical_results(scenario, rnd):
    docs, receipts, bills, billed = scenario
    po = po_4471(qbo_billed=billed)

    def run(d, r, b):
        inp = build(docs=tuple(d), po=po, imports=(class_a(),), receipts=tuple(r), bills=tuple(b))
        return evaluate(inp), input_fingerprint(inp)

    reference, fp = run(docs, receipts, bills)
    perms = list(itertools.islice(itertools.permutations(docs), 24))
    for perm in perms:
        r2, b2 = list(receipts), list(bills)
        rnd.shuffle(r2)
        rnd.shuffle(b2)
        result, fp2 = run(perm, r2, b2)
        assert result == reference
        assert fp2 == fp
    # Invariants that must hold for every generated set.
    for e in reference.exceptions:
        assert e.reported_amount >= 0
    for line in reference.lines:
        if line.status.value == "matched":
            assert line.receipt_line_count > 0
    per_line: dict[str, D] = {}
    for e in reference.exceptions:
        if e.line_id:
            per_line[e.line_id] = per_line.get(e.line_id, D(0)) + e.reported_amount
    amounts = {ln.id: ln.amount for d in docs for ln in d.lines}
    for line_id, reported in per_line.items():
        assert reported <= abs(amounts[line_id])
