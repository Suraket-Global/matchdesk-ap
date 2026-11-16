"""B14 (2026-11-17): the two Critical findings of the independent acceptance test. Synthetic data.

C1. A match result must never stay "out of date": an action that changes match inputs queues a
    re-match that completes, and an action that changes none (a receiving file left as a draft)
    marks nothing out of date.
C2. A decided credit clears exactly what it covers and raises no new finding on the same units.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.exceptions import request_run
from matchdesk.exceptions.models import MatchRun
from matchdesk.tenancy import session

from .b14_helpers import (
    OCT,
    drain,
    exc_of,
    excs,
    match,
    out_of_date,
    second_supplier,
    settled,
    vendor_credit,
)
from .seed import add_invoice, add_receipt, add_user, attest, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def two_suppliers(engine, client, name):  # type: ignore[no-untyped-def]
    """Supplier 1: 60 received, 60 + 40 invoiced (the second invoice is over received by 40 x 4.20 =
    168.00, possibly credited by VC-9). Supplier 2: one invoice at a higher price."""
    w = make_tenant(engine, name)
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "60", date(2026, 9, 28))
    a1 = add_invoice(engine, w, "a1", "INV-A1", date(2026, 10, 2), "60")
    a2 = add_invoice(engine, w, "a2", "INV-A2", date(2026, 10, 9), "40")
    vendor_credit(engine, w, "168.00", date(2026, 10, 20))
    w2 = second_supplier(engine, w)
    add_receipt(engine, w2, "100", date(2026, 9, 28), row=2)
    b1 = add_invoice(engine, w2, "b1", "INV-B1", date(2026, 10, 3), "10", price="4.50")
    match(client, engine, w.headers, [a1, a2, b1])
    assert out_of_date(engine, w) == []
    return w, w2, ctrl, (a1, a2, b1)


def all_suppliers_run(client, ctrl, engine, value="0.10"):  # type: ignore[no-untyped-def]
    """An ordinary action whose re-match covers every supplier at once (the tester used a tolerance
    save; a QuickBooks read does the same)."""
    r = client.put("/api/v1/tolerances/default", json={"price_tol_abs": value}, headers=ctrl)
    assert r.status_code == 200, r.text
    drain(engine)


def report_reasons(client, headers) -> list[str]:  # type: ignore[no-untyped-def]
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=headers)
    assert d.status_code in (200, 201), d.text
    return list(d.json()["blocking"])


def test_c1a_a_receiving_file_left_as_a_draft_marks_nothing_out_of_date(app_engine, client):  # type: ignore[no-untyped-def]
    w, _w2, ctrl, _ids = two_suppliers(app_engine, client, "Fictional Distributor B14-C1a")
    attest(app_engine, w)
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("second.csv", b"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-12\n", "text/csv")},
        data={"evidence_class": "A", "source_type": "spreadsheet"},
        headers=w.headers,
    )
    assert up.status_code == 201 and up.json()["state"] == "draft", up.text
    settled(app_engine, w)
    cols = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "uom": "UOM",
    }
    m = client.put(
        f"/api/v1/receiving/imports/{up.json()['id']}/mapping", json={"columns": cols}, headers=w.headers
    )
    assert m.status_code == 200 and m.json()["state"] != "succeeded", m.text  # "Check rows": still a draft
    settled(app_engine, w)
    assert not any("out of date" in r or "out-of-date" in r for r in report_reasons(client, ctrl))


def test_c1b_credit_decision_after_an_all_supplier_run_leaves_nothing_out_of_date(app_engine, client):  # type: ignore[no-untyped-def]
    w, _w2, ctrl, (_a1, a2, _b1) = two_suppliers(app_engine, client, "Fictional Distributor B14-C1b")
    all_suppliers_run(client, ctrl, app_engine)
    settled(app_engine, w)
    e = exc_of(app_engine, w, a2, "qty_over_received")
    assert e.possibly_credited_bill_id is not None
    r = client.post(
        f"/api/v1/exceptions/{e.id}/credit-decision",
        json={"decision": "credited"},
        headers={**ctrl, "If-Match": str(e.version)},
    )
    assert r.status_code == 200, r.text
    settled(app_engine, w)
    assert not any("out of date" in x or "out-of-date" in x for x in report_reasons(client, ctrl))


def test_c1c_document_deletion_after_an_all_supplier_run_leaves_nothing_out_of_date(app_engine, client):  # type: ignore[no-untyped-def]
    w, _w2, ctrl, _ids = two_suppliers(app_engine, client, "Fictional Distributor B14-C1c")
    all_suppliers_run(client, ctrl, app_engine)
    r = client.post(
        f"/api/v1/documents/{w.documents['a1']}/deletion-requests",
        json={"reason": "uploaded twice (synthetic)"},
        headers=ctrl,
    )
    assert r.status_code in (200, 201), r.text
    settled(app_engine, w)
    assert not any("out of date" in x or "out-of-date" in x for x in report_reasons(client, ctrl))


def test_c1_a_run_never_spans_two_suppliers_and_one_supplier_cannot_date_another(app_engine, client):  # type: ignore[no-untyped-def]
    w, w2, _ctrl, (a1, a2, b1) = two_suppliers(app_engine, client, "Fictional Distributor B14-C1d")
    with session(w.tenant_id, app_engine) as s:
        scopes = [sorted(r.scope["invoice_ids"]) for r in s.scalars(select(MatchRun)).all()]
    assert sorted(scopes) == sorted([sorted([str(a1), str(a2)]), [str(b1)]])
    # A new invoice of supplier 2 re-matches supplier 2 only; supplier 1 stays current.
    with session(w.tenant_id, app_engine) as s:
        before = s.scalar(select(MatchRun.id).where(MatchRun.scope["invoice_ids"].contains([str(a1)])))
    b2 = add_invoice(app_engine, w2, "b2", "INV-B2", date(2026, 10, 12), "5")
    match(client, app_engine, w.headers, [b2])
    settled(app_engine, w)
    with session(w.tenant_id, app_engine) as s:
        runs = s.scalars(select(MatchRun).where(MatchRun.scope["invoice_ids"].contains([str(a1)]))).all()
        assert [r.id for r in runs] == [before]
        # Asking again for everything creates nothing: every result is current.
        _run, created = request_run(s, w.tenant_id, [a1, a2, b1, b2])
        assert created is False


def test_c1_results_stored_by_a_run_over_several_suppliers_are_healed_by_the_next_request(
    app_engine, owner_engine, client
):  # type: ignore[no-untyped-def]
    """Results stored before B14 by one run over several suppliers go out of date for all of them
    when one supplier changes. The next request, or the worker's minute tick, re-matches them."""
    from matchdesk.exceptions import rematch_out_of_date

    w, _w2, _ctrl, (a1, a2, b1) = two_suppliers(app_engine, client, "Fictional Distributor B14-C1e")
    # Rebuild the pre-B14 shape as the owner (the app role may not rewrite a stored result): one
    # succeeded run holding every current result, its fingerprint that of an input since changed.
    with session(w.tenant_id, app_engine) as s:
        keep = s.scalars(select(MatchRun).order_by(MatchRun.created_at)).first()
        assert keep is not None
        keep.scope = {"invoice_ids": sorted(str(i) for i in (a1, a2, b1))}
        keep.input_fingerprint = b"\x00" * 32
        keep_id = keep.id
    with owner_engine.begin() as c:
        c.execute(
            text("update line_matches set match_run_id = :r where tenant_id = :t and is_current"),
            {"r": keep_id, "t": w.tenant_id},
        )
    assert len(out_of_date(app_engine, w)) == 3
    with session(w.tenant_id, app_engine) as s:
        assert rematch_out_of_date(s, w.tenant_id) == 2  # one run per supplier
    settled(app_engine, w)
    with session(w.tenant_id, app_engine) as s:
        assert rematch_out_of_date(s, w.tenant_id) == 0


def test_c2_credited_decision_raises_no_finding_on_the_same_units(app_engine, client):  # type: ignore[no-untyped-def]
    """FF-1003 of the acceptance test: ordered 80, received 60, invoiced 60 then 40 at 4.20. The
    second invoice is over received by 40 (168.00) and over ordered by 20 (84.00, counted under the
    first). The controller decides the 168.00 was credited by VC-9: 60 units remain billed against 80
    ordered, so nothing is left to flag, in the queue, the report or the refund figure."""
    w = make_tenant(app_engine, "Fictional Distributor B14-C2")
    _c, ctrl = add_user(app_engine, w, "controller")
    with session(w.tenant_id, app_engine) as s:
        from matchdesk.qbo.models import PoLineRow

        s.get(PoLineRow, w.po_line_id).qty_ordered = 80  # type: ignore[union-attr]
    add_receipt(app_engine, w, "60", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "INV-C2A", date(2026, 10, 2), "60")
    b = add_invoice(app_engine, w, "b", "INV-C2B", date(2026, 10, 9), "40")
    vendor_credit(app_engine, w, "168.00", date(2026, 10, 20))
    match(client, app_engine, w.headers, [a, b])
    over_received = exc_of(app_engine, w, b, "qty_over_received")
    over_ordered = exc_of(app_engine, w, b, "qty_over_ordered")
    assert str(over_received.variance_amount) == "168.00" and over_received.possibly_credited_bill_id
    assert str(over_ordered.variance_amount) == "84.00" and str(over_ordered.reported_amount) == "0.00"
    r = client.post(
        f"/api/v1/exceptions/{over_received.id}/credit-decision",
        json={"decision": "credited"},
        headers={**ctrl, "If-Match": str(over_received.version)},
    )
    assert r.status_code == 200, r.text
    settled(app_engine, w)
    after = {e.type: e for e in excs(app_engine, w, b)}
    assert after["qty_over_received"].resolution_code == "resolved_by_credit"
    sibling = after["qty_over_ordered"]
    assert (sibling.status, sibling.resolution_code) == ("resolved", "resolved_by_credit")
    assert str(sibling.reported_amount) == "0.00" and sibling.qualifying is False
    # Queue: nothing open on the document, and no money in the scope total.
    q = client.get("/api/v1/exceptions", params={"status": "open"}, headers=w.headers).json()
    assert [i for i in q["items"] if i["invoice_id"] == str(b)] == []
    # Report and refund figure.
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl)
    assert d.status_code in (200, 201), d.text
    assert d.json()["findings_amount"] == "0.00" and d.json()["qualifying_amount"] == "0.00", d.json()
    full = client.get(f"/api/v1/reports/backtest/{d.json()['id']}", headers=ctrl).json()
    assert full["flagged_amount"] == "0.00" and [f for f in full["findings"] if f["qualifying"]] == []
    ok = client.post(f"/api/v1/reports/backtest/{d.json()['id']}/approve", headers=ctrl)
    assert ok.status_code == 200, ok.text
    ev = client.get(f"/api/v1/reports/backtest/{d.json()['id']}/refund-evaluation", headers=ctrl)
    assert ev.status_code == 200, ev.text
    assert D(ev.json()["qualifying_total"]) == D("0") and ev.json()["refund_due"] is True, ev.json()


def test_c1_invariant_no_ordinary_action_leaves_a_result_out_of_date(app_engine, client):  # type: ignore[no-untyped-def]
    """The general invariant behind C1, walked through the API: after each ordinary action and one
    drain of the worker (the minute tick is never run here), every job is done and no current result
    is out of date. Each step is an action that changes match inputs, or one that must not."""
    from matchdesk.core import text_pdf
    from matchdesk.extraction.local_pdf import LocalPdfExtractor
    from matchdesk.intake import process_document
    from matchdesk.intake.models import InvoiceRow
    from matchdesk.qbo.models import PoLineRow
    from matchdesk.tenancy import enqueue

    w, w2, ctrl, (_a1, a2, b1) = two_suppliers(app_engine, client, "Fictional Distributor B14-C1inv")
    _c2, ctrl2 = add_user(app_engine, w, "controller")
    attest(app_engine, w)
    steps: list[str] = []

    def step(name: str, r=None, ok=(200, 201, 202)) -> None:  # type: ignore[no-untyped-def]
        if r is not None:
            assert r.status_code in ok, f"{name}: {r.status_code} {r.text}"
        settled(app_engine, w)
        steps.append(name)

    # 1. Tolerances: account default, then one supplier.
    step(
        "default tolerance",
        client.put("/api/v1/tolerances/default", json={"price_tol_abs": "0.05"}, headers=ctrl),
    )
    step(
        "supplier tolerance",
        client.put(f"/api/v1/tolerances/{w2.vendor_id}", json={"price_tol_abs": "0.01"}, headers=ctrl),
    )
    # 2. Receiving: a draft, "Check rows", a committed class A log declared complete (coverage is read
    #    for every supplier), its declaration changed, then voided.
    cols = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "uom": "UOM",
    }
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("log.csv", b"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-12\n", "text/csv")},
        data={"evidence_class": "A", "source_type": "spreadsheet"},
        headers=w.headers,
    )
    step("receiving draft", up)
    imp = up.json()["id"]
    step(
        "check rows",
        client.put(f"/api/v1/receiving/imports/{imp}/mapping", json={"columns": cols}, headers=w.headers),
    )
    step(
        "declare complete",
        client.put(
            f"/api/v1/receiving/imports/{imp}/declaration",
            json={
                "declared_complete": True,
                "coverage_start": "2026-08-01",
                "coverage_end": "2026-11-30",
                "kept_by_name": "Synthetic receiver",
            },
            headers=w.headers,
        ),
    )
    step("commit receiving", client.post(f"/api/v1/receiving/imports/{imp}/commit", headers=w.headers))
    step(
        "void receiving",
        client.post(
            f"/api/v1/receiving/imports/{imp}/void",
            json={"reason": "wrong file (synthetic)"},
            headers=w.headers,
        ),
    )
    # 3. An invoice that needs review arrives, is corrected, then confirmed.
    pdf = text_pdf(
        [
            "INVOICE",
            "Vendor: Fictional Supplier T",
            "Invoice No: INV-A9",
            "Invoice Date: 2026-10-10",
            "PO Number: 4471",
            "Currency: CAD",
            "W-100   Synthetic widget   2  EA   4.20   8.40",
            "Subtotal: 8.40",
            "Tax: 0.00",
            "Total: 9.99",
        ]
    )
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    f = client.post(
        f"/api/v1/intake/batches/{batch}/files",
        files={"file": ("a9.pdf", pdf, "application/pdf")},
        headers={**w.headers, "Idempotency-Key": "b14-a9"},
    )
    assert f.status_code == 201, f.text
    process_document(app_engine, w.tenant_id, uuid.UUID(f.json()["id"]), LocalPdfExtractor())
    step("invoice that needs review")
    with session(w.tenant_id, app_engine) as s:
        a9 = s.scalar(select(InvoiceRow.id).where(InvoiceRow.doc_number == "INV-A9"))
    rev = client.get(f"/api/v1/invoices/{a9}", headers=w.headers).json()["review"]
    fix = client.patch(
        f"/api/v1/invoices/{a9}/extraction",
        json={"fields": {"total": "8.40"}},
        headers={**w.headers, "If-Match": str(rev["version"])},
    )
    step("correction saved", fix)
    step(
        "extraction confirmed",
        client.post(
            f"/api/v1/invoices/{a9}/confirm-extraction",
            headers={**w.headers, "If-Match": str(fix.json()["version"])},
        ),
    )
    # 4. Aliases: retire, create with a conversion (waits for approval), approve.
    alias = next(
        a
        for a in client.get("/api/v1/aliases", headers=w.headers).json()["items"]
        if a["vendor_id"] == str(w.vendor_id)
    )
    step(
        "alias retired",
        client.post(
            f"/api/v1/aliases/{alias['id']}/deactivate",
            json={"reason": "units wrong (synthetic)"},
            headers={**w.headers, "If-Match": str(alias["version"])},
        ),
    )
    step(
        "alias with conversion created",
        client.post(
            "/api/v1/aliases",
            headers=ctrl,
            json={
                "vendor_id": str(w.vendor_id),
                "supplier_item_code": "W-100",
                "item_id": str(w.item_id),
                "conversion_factor": "2",
                "supplier_uom": "EA",
                "item_uom": "EA",
            },
        ),
    )
    ap = client.get("/api/v1/approvals", params={"subject_type": "alias_conversion"}, headers=ctrl).json()[
        "items"
    ][0]
    step(
        "conversion returned",
        client.post(
            f"/api/v1/approvals/{ap['id']}/decision",
            json={"decision": "return", "note": "factor is 1 (synthetic)"},
            headers={**ctrl2, "If-Match": str(ap["version"])},
        ),
    )
    step(
        "alias created",
        client.post(
            "/api/v1/aliases",
            headers=ctrl,
            json={"vendor_id": str(w.vendor_id), "supplier_item_code": "W-100", "item_id": str(w.item_id)},
        ),
    )
    # 5. A purchase order changed in QuickBooks (what a read enqueues), for one supplier.
    with session(w.tenant_id, app_engine) as s:
        s.get(PoLineRow, w2.po_line_id).qty_ordered = D("5")  # type: ignore[union-attr]
        enqueue(
            s,
            "match_request",
            w.tenant_id,
            {"po_ids": [str(w2.po_id)], "trigger": "po_change"},
            str(uuid.uuid4()),
        )
    step("purchase order changed")
    # 6. Decisions: credit, then a controller's "not received" on another account line, reopen.
    e = exc_of(app_engine, w, a2, "qty_over_received")
    step(
        "credit decided",
        client.post(
            f"/api/v1/exceptions/{e.id}/credit-decision",
            json={"decision": "credited"},
            headers={**ctrl, "If-Match": str(e.version)},
        ),
    )
    over = exc_of(app_engine, w, b1, "qty_over_ordered")
    step(
        "exception resolved",
        client.post(
            f"/api/v1/exceptions/{over.id}/resolutions",
            json={"code": "confirmed_overbilling", "note": "synthetic"},
            headers={**ctrl, "If-Match": str(over.version)},
        ),
    )
    over = exc_of(app_engine, w, b1, "qty_over_ordered")
    step(
        "exception reopened",
        client.post(f"/api/v1/exceptions/{over.id}/reopen", headers={**ctrl, "If-Match": str(over.version)}),
    )
    # 7. A possible duplicate (same total within 7 days) decided.
    b3 = add_invoice(app_engine, w2, "b3", "INV-B3", date(2026, 10, 5), "10", price="4.50")
    match(client, app_engine, w.headers, [b3])
    step("invoice added")
    pd = exc_of(app_engine, w, b3, "possible_duplicate")
    step(
        "duplicate decided",
        client.post(
            f"/api/v1/exceptions/{pd.id}/duplicate-decision",
            json={"decision": "not_duplicate"},
            headers={**ctrl, "If-Match": str(pd.version)},
        ),
    )
    # 8. Documents deleted: one of each supplier.
    for key in ("a1", "b1"):
        step(
            f"document {key} deleted",
            client.post(
                f"/api/v1/documents/{w.documents[key]}/deletion-requests",
                json={"reason": "uploaded twice (synthetic)"},
                headers=ctrl,
            ),
        )
    # 9. The "no receiving records" statement is refused while a log counts; either way nothing is stale.
    step(
        "no-receiving statement",
        client.post("/api/v1/onboarding/no-receiving-declaration", headers=ctrl),
        ok=(201, 409, 422),
    )
    assert len(steps) == 23
    # The report of the month is never blocked by out-of-date results.
    assert not any("out of date" in x or "out-of-date" in x for x in report_reasons(client, ctrl))
