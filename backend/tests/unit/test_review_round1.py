"""Regression tests for review round 1 of B1 (B1-002 to B1-009 engine and lint cases)."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from matchdesk.extraction import FakeExtractor
from matchdesk.matching import (
    DocLine,
    DuplicateDecision,
    ExceptionStatus,
    ExceptionType,
    LineKind,
    LineStatus,
    PoLine,
    Tolerance,
    ValueClass,
    evaluate,
)
from matchdesk.reporting import calculate_refund

from .builders import D, alias, build, class_a, credit_note, invoice, po_4471, qbo_bill, receipt

ROOT = Path(__file__).resolve().parents[2]
SEP, OCT = date(2026, 9, 10), date(2026, 10, 8)
T = ExceptionType


def types(res, line_id=None, document_id=None):
    return sorted(e.type.value for e in res.exceptions_for(line_id=line_id, document_id=document_id))


@pytest.mark.parametrize("billed", [None, "120"])
def test_b1_002_unresolved_earlier_line_does_not_hide_its_qbo_bill(billed):
    inp = build(
        docs=(invoice("sep", "INV-0900", SEP, "60", code="W-100-X"), invoice("oct", "INV-1000", OCT, "60")),
        tests=("oct",),
        po=po_4471(qbo_billed=billed),
        imports=(class_a(),),
        receipts=(receipt("r1", "60", SEP),),
        bills=(
            qbo_bill("b-sep", "INV-0900", SEP, "60", "252.00"),
            qbo_bill("b-oct", "INV-1000", OCT, "60", "252.00"),
        ),
    )
    res = evaluate(inp)
    line = res.line("oct-l1")
    assert line.status != LineStatus.MATCHED
    assert line.qty_invoiced_cum_net == D("120")
    [over] = [e for e in res.exceptions if e.type == T.QTY_OVER_RECEIVED]
    assert over.reported_amount == D("252.00") and over.qualifying


def test_b1_002_unresolved_earlier_line_without_bill_blocks_as_history_incomplete():
    inp = build(
        docs=(invoice("sep", "INV-0900", SEP, "60", code="W-100-X"), invoice("oct", "INV-1000", OCT, "60")),
        tests=("oct",),
        imports=(class_a(),),
        receipts=(receipt("r1", "120", SEP),),
    )
    res = evaluate(inp)
    assert res.line("oct-l1").status == LineStatus.EXCEPTION
    assert "history_incomplete" in types(res, line_id="oct-l1")
    # A later unresolved invoice does not affect an earlier line.
    later = build(
        docs=(
            invoice("oct", "INV-1000", OCT, "60"),
            invoice("nov", "INV-1100", date(2026, 11, 2), "60", code="X"),
        ),
        tests=("oct",),
        imports=(class_a(),),
        receipts=(receipt("r1", "120", SEP),),
    )
    assert evaluate(later).line("oct-l1").status == LineStatus.MATCHED


def test_b1_003_credit_note_uploaded_twice_is_not_a_finding_and_nets_once():
    cn1 = credit_note("cn1", "CN-7", date(2026, 10, 20), qty="40", amount="168.00", references="INV-1")
    cn2 = replace(
        credit_note("cn2", "CN-7", date(2026, 10, 21), qty="40", amount="168.00", references="INV-1"),
        file_sha256=b"other-file",
    )
    res = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "100"), cn1, cn2),
            imports=(class_a(),),
            receipts=(receipt("r1", "60", OCT),),
        )
    )
    [dup] = [e for e in res.exceptions if e.document_id == "cn2" and e.type == T.DUPLICATE]
    assert dup.value_class == ValueClass.NONE and not dup.qualifying and dup.reported_amount == D("0.00")
    assert res.line("i1-l1").qty_invoiced_cum_net == D("60")  # netted once, not twice
    assert calculate_refund(res.exceptions).qualifying_total == D("0.00")


def test_b1_003_possible_duplicate_credit_is_not_netted_until_decided():
    inv = invoice("i1", "INV-1", OCT, "100")
    cn1 = credit_note("cn1", "CN-7", date(2026, 10, 20), qty="40", amount="168.00", references="INV-1")
    cn2 = credit_note("cn2", "CN-7A", date(2026, 10, 22), qty="40", amount="168.00", references="INV-1")
    base = {"imports": (class_a(),), "receipts": (receipt("r1", "20", OCT),)}
    res = evaluate(build(docs=(inv, cn1, cn2), **base))
    assert res.line("i1-l1").qty_invoiced_cum_net == D("60")
    [pd] = [e for e in res.exceptions if e.type == T.POSSIBLE_DUPLICATE]
    assert pd.document_id == "cn2" and not pd.qualifying
    cleared = evaluate(
        build(docs=(inv, cn1, cn2), duplicate_decisions=(("cn2", DuplicateDecision.NOT_A_DUPLICATE),), **base)
    )
    assert cleared.line("i1-l1").qty_invoiced_cum_net == D("20")


@pytest.mark.parametrize("qtol", ["0", "10"])
def test_b1_004_net_zero_receipts_never_pass_and_keep_the_finding(qtol):
    res = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "10"),),
            imports=(class_a(),),
            receipts=(receipt("r1", "10", OCT), receipt("r2", "-10", date(2026, 10, 12))),
            tolerance=Tolerance(qty_tolerance=D(qtol)),
        )
    )
    assert res.line("i1-l1").status == LineStatus.EXCEPTION
    # B1-012: received and fully returned is evidence, not its absence: a qualifying finding.
    [over] = [e for e in res.exceptions if e.type == T.QTY_OVER_RECEIVED]
    assert over.sub_reason is not None and over.sub_reason.value == "returned_no_credit"
    assert (over.variance_amount, over.reported_amount, over.qualifying) == (D("42.00"), D("42.00"), True)
    assert "receipt_absent" not in types(res)
    assert calculate_refund(res.exceptions).qualifying_total == D("42.00")


@pytest.mark.parametrize("covered", [False, True])
def test_b1_012_full_return_is_a_qualifying_finding_covered_or_not(covered):
    imp = class_a(start=date(2026, 8, 1), end=date(2026, 12, 31), complete=True) if covered else class_a()
    res = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "10"),),
            imports=(imp,),
            receipts=(receipt("r1", "10", OCT), receipt("r2", "-10", date(2026, 10, 12))),
        )
    )
    assert res.line("i1-l1").status == LineStatus.EXCEPTION
    assert calculate_refund(res.exceptions).qualifying_total == D("42.00")
    # A credit note for the returned quantity removes the finding, but the line still never passes.
    cn = credit_note("cn", "CN-1", date(2026, 10, 14), qty="10", amount="42.00", references="INV-1")
    credited = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "10"), cn),
            imports=(imp,),
            receipts=(receipt("r1", "10", OCT), receipt("r2", "-10", date(2026, 10, 12))),
        )
    )
    assert calculate_refund(credited.exceptions).qualifying_total == D("0.00")
    assert credited.line("i1-l1").status != LineStatus.MATCHED


def test_b1_005_freight_is_cumulative_against_the_po_amount():
    po = po_4471(
        extra_lines=(
            PoLine(
                "pol-f", 9, None, D("1"), None, D("50.00"), charge_kind=LineKind.FREIGHT, amount=D("50.00")
            ),
        )
    )

    def freight(doc, amount="50.00"):
        return DocLine(id=f"{doc}-f", line_no=2, kind=LineKind.FREIGHT, amount=D(amount))

    docs = tuple(
        invoice(f"i{k}", f"INV-{k}", date(2026, 10, k), "10", extra=(freight(f"i{k}", a),))
        for k, a in ((1, "30.00"), (2, "30.00"), (3, "50.00"))
    )
    res = evaluate(build(docs=docs, po=po, imports=(class_a(),), receipts=(receipt("r1", "30", OCT),)))
    assert [res.line(f"i{k}-f").status for k in (1, 2, 3)] == [
        LineStatus.CHARGE_OK,
        LineStatus.EXCEPTION,
        LineStatus.EXCEPTION,
    ]
    amounts = [e.variance_amount for e in res.exceptions if e.type == T.UNMATCHED_CHARGE]
    assert sorted(amounts) == [D("10.00"), D("50.00")]  # 60 - 50, then the whole third charge


def test_b1_008_units_assumed_only_when_the_alias_does_not_convert():
    no_unit = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "5", "50.40", uom=None),),
            aliases=(alias("12", approved=True, supplier_uom="CS", item_uom="EA"),),
            imports=(class_a(),),
            receipts=(receipt("r1", "60", OCT),),
        )
    )
    assert types(no_unit) == ["uom_unresolved"]
    factor_one = evaluate(
        build(
            docs=(invoice("i1", "INV-1", OCT, "5", "50.40", uom="CS"),),
            aliases=(alias("1", approved=False, supplier_uom="CS", item_uom="EA"),),
            imports=(class_a(),),
            receipts=(receipt("r1", "60", OCT),),
        )
    )
    assert types(factor_one) == ["alias_unconfirmed"]


def test_floats_refused_at_the_engine_boundary():
    with pytest.raises(TypeError):
        evaluate(build(docs=(replace(invoice("i1", "INV-1", OCT, "10"), total=4.2),)))  # type: ignore[arg-type]


def test_tie_rule_is_explicit_priority():
    res = evaluate(
        build(
            docs=(invoice("i", "INV-1", OCT, "110"),),
            imports=(class_a(),),
            receipts=(receipt("r", "100", OCT),),
        )
    )
    by = {e.type: e for e in res.exceptions}
    assert by[T.QTY_OVER_RECEIVED].reported_amount == D("42.00")
    assert by[T.QTY_OVER_ORDERED].reported_amount == D("0.00")
    assert all(e.status == ExceptionStatus.OPEN for e in res.exceptions)


def test_b1_007_fake_extractor_reads_decimals_not_floats():
    body = {"lines": [{"qty": 3, "unit_price": 0.335, "amount": 1.01}], "total": 1.01}
    out = FakeExtractor().extract(b"%FAKE-PDF\n" + json.dumps(body).encode()).output
    assert isinstance(out["lines"][0]["unit_price"], Decimal) and isinstance(out["total"], Decimal)


def test_b1_009_top_level_import_rule_is_enforced(tmp_path):
    script = ROOT / "scripts" / "check_imports.py"
    ok = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    pkg = tmp_path / "matchdesk"
    (pkg / "reporting").mkdir(parents=True)
    (pkg / "reporting" / "bad.py").write_text("from matchdesk.exceptions.store import store_result\n")
    (pkg / "exceptions").mkdir()
    (pkg / "exceptions" / "ok.py").write_text("from matchdesk.qbo.models import Vendor\n")
    bad = subprocess.run([sys.executable, str(script), str(pkg)], check=False, capture_output=True, text=True)
    assert bad.returncode == 1
    assert "reporting imports matchdesk.exceptions.store" in bad.stdout
    assert "exceptions/ok.py" not in bad.stdout
