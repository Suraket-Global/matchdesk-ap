"""B14 (2026-11-17): the Minor findings of the independent acceptance test that live in the API.
Web-only minors are in web/src/b14-acceptance.test.tsx. Synthetic data."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.core import RecordingMailer
from matchdesk.exceptions.models import ToleranceRule
from matchdesk.identity import User, enroll_operator, issue_session
from matchdesk.tenancy import global_session, session

from .b14_helpers import OCT, drain, match
from .seed import add_invoice, add_receipt, add_user, attest, auth_headers, make_tenant

pytestmark = pytest.mark.integration
MAIL = RecordingMailer()


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(mailer=MAIL), raise_server_exceptions=False)


def make_operator(engine):  # type: ignore[no-untyped-def]
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        u = User(email=email, display_name="Synthetic Operator")
        s.add(u)
        s.flush()
        uid = u.id
    enroll_operator(engine, email)
    return uid, auth_headers(issue_session(engine, uid, None))


def twice(call, n: int = 2):  # type: ignore[no-untyped-def]
    """The same request ``n`` times at the same moment (a double press of a button)."""
    gate = threading.Barrier(n)

    def one(_i: int):  # type: ignore[no-untyped-def]
        gate.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=n) as pool:
        return sorted(r.status_code for r in pool.map(one, range(n)))


# --- m1 ---------------------------------------------------------------------------------------------


def test_m1_a_double_press_never_answers_500_and_acts_once(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-m1")
    _c, ctrl = add_user(app_engine, w, "controller")
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "a", "INV-M1", date(2026, 10, 6), "10", price="4.50")
    add_receipt(app_engine, w, "10", date(2026, 9, 28))
    match(client, app_engine, w.headers, [inv])

    # Receiving commit.
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("log.csv", b"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-12\n", "text/csv")},
        data={"evidence_class": "A", "source_type": "spreadsheet"},
        headers=w.headers,
    ).json()
    cols = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "uom": "UOM",
    }
    assert (
        client.put(
            f"/api/v1/receiving/imports/{up['id']}/mapping", json={"columns": cols}, headers=w.headers
        ).status_code
        == 200
    )
    got = twice(lambda: client.post(f"/api/v1/receiving/imports/{up['id']}/commit", headers=w.headers))
    assert got == [200, 200], got
    with session(w.tenant_id, app_engine) as s:
        assert (
            s.scalar(
                text("select count(*) from receipt_lines where receiving_import_id = :i"), {"i": up["id"]}
            )
            == 1
        )

    # Tolerance save: one new version, not two.
    got = twice(
        lambda: client.put("/api/v1/tolerances/default", json={"price_tol_abs": "0.07"}, headers=ctrl)
    )
    assert got == [200, 200], got
    with session(w.tenant_id, app_engine) as s:
        rules = s.scalars(select(ToleranceRule).where(ToleranceRule.vendor_id.is_(None))).all()
        assert len(rules) == 1 and len([r for r in rules if r.valid_to is None]) == 1
    drain(app_engine)

    # Governing report version (its own account: nothing waits for approval there).
    _op, oh = make_operator(app_engine)
    g = make_tenant(app_engine, "Fictional Distributor B14-m1g")
    _gc, gctrl = add_user(app_engine, g, "controller")
    add_receipt(app_engine, g, "10", date(2026, 9, 28))
    match(
        client, app_engine, g.headers, [add_invoice(app_engine, g, "a", "INV-M1G", date(2026, 10, 6), "10")]
    )
    terms = {
        "price": "500.00",
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "refund_threshold": "500.00",
    }
    assert (
        client.put(f"/api/v1/operator/tenants/{g.tenant_id}/pilot", json=terms, headers=oh).status_code == 200
    )
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=gctrl).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=gctrl).status_code == 200
    got = twice(
        lambda: client.put("/api/v1/pilot/governing-report", json={"report_id": d["id"]}, headers=gctrl)
    )
    assert got == [200, 200], got

    # Weekly summary by hand: one email per controller, however many presses.
    before = len(MAIL.sent)
    got = twice(
        lambda: client.post("/api/v1/weekly-summary/send", json={"week_start": "2026-10-05"}, headers=ctrl)
    )
    assert 500 not in got and got[0] == 200, got
    assert len(MAIL.sent) - before == 1

    # Archive: one export.
    got = twice(lambda: client.post("/api/v1/exports/archive", headers=ctrl))
    assert got == [202, 202], got
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(text("select count(*) from archive_exports")) == 1

    # Support request: one open request.
    ask = {"hours": 2, "reason": "synthetic check"}
    got = twice(
        lambda: client.post(f"/api/v1/operator/tenants/{w.tenant_id}/support-grants", json=ask, headers=oh)
    )
    assert got == [201, 201], got
    assert len(client.get("/api/v1/support-grants", headers=ctrl).json()["items"]) == 1

    # Invitation: one open invitation.
    invite = {"email": f"m1.{uuid.uuid4().hex[:6]}@example.invalid", "role": "clerk"}
    got = twice(lambda: client.post("/api/v1/invitations", json=invite, headers=ctrl))
    assert got == [201, 201], got
    assert len(client.get("/api/v1/invitations", headers=ctrl).json()["items"]) == 1

    # Account deletion request: one request; the second is told it is already open.
    ask = {"confirm_name": "Fictional Distributor B14-m1", "acknowledge_incomplete_archive": True}
    got = twice(lambda: client.post("/api/v1/account/deletion-requests", json=ask, headers=ctrl))
    assert got == [201, 409], got

    # Account creation: one account.
    name = f"Fictional Doubleco {uuid.uuid4().hex[:6]}"
    got = twice(lambda: client.post("/api/v1/operator/tenants", json={"name": name}, headers=oh))
    assert got == [201, 409], got


def test_m1_an_unexpected_error_is_logged_with_its_request_and_traceback(app_engine, caplog):  # type: ignore[no-untyped-def]
    import logging

    app = create_app(mailer=MAIL)

    @app.get("/healthz/_b14_boom")
    def boom() -> None:
        raise RuntimeError("synthetic failure")

    c = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR):
        r = c.get("/healthz/_b14_boom")
    assert r.status_code == 500 and r.json()["title"] == "Something went wrong on our side"
    rec = next(x for x in caplog.records if x.getMessage() == "unhandled_error")
    assert (rec.path, rec.method, rec.reason) == ("/healthz/_b14_boom", "GET", "RuntimeError")
    assert rec.exc_info and "synthetic failure" in str(rec.exc_info[1])


# --- m4 ---------------------------------------------------------------------------------------------


def test_m4_receiving_rows_with_a_negative_quantity_or_a_future_date_are_pointed_out(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-m4")
    attest(app_engine, w)
    rows = b"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-12\n4471,2,-5,EA,2026-10-13\n4471,2,3,EA,2099-01-01\n4471,2,0,EA,2026-10-14\n4471,2,1,CS,2026-10-14\n"
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("odd.csv", rows, "text/csv")},
        data={"evidence_class": "A", "source_type": "spreadsheet"},
        headers=w.headers,
    ).json()
    cols = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "uom": "UOM",
    }
    v = client.put(
        f"/api/v1/receiving/imports/{up['id']}/mapping", json={"columns": cols}, headers=w.headers
    ).json()["validation"]
    assert (v["rows_valid"], v["rows_rejected"]) == (3, 2)  # a return and a future date stay valid rows
    assert [(r["row"], r["reason"]) for r in v["warning_rows"]] == [
        (3, "negative_quantity"),
        (4, "future_date"),
    ]
    assert sorted(r["reason"] for r in v["rejected_rows"]) == ["qty_zero", "uom_differs_from_po"]
    # The same rows are pointed out after a reload of the draft.
    again = client.get(f"/api/v1/receiving/imports/{up['id']}", headers=w.headers).json()
    assert [r["reason"] for r in again["warning_rows"]] == ["negative_quantity", "future_date"]


# --- m6: a supplier that matches no vendor needs review and blocks approval ---------------------------


def test_m6_an_unknown_supplier_needs_review_and_blocks_the_report(app_engine, client):  # type: ignore[no-untyped-def]
    from matchdesk.core import text_pdf
    from matchdesk.extraction.local_pdf import LocalPdfExtractor
    from matchdesk.intake import process_document

    w = make_tenant(app_engine, "Fictional Distributor B14-m6")
    _c, ctrl = add_user(app_engine, w, "controller")
    pdf = text_pdf(
        [
            "INVOICE",
            "Vendor: A Supplier Name QuickBooks Does Not Hold",
            "Invoice No: LONG-1",
            "Invoice Date: 2026-10-10",
            "PO Number: 4471",
            "Currency: CAD",
            "W-100   Synthetic widget   2  EA   4.20   8.40",
            "Subtotal: 8.40",
            "Tax: 0.00",
            "Total: 8.40",
        ]
    )
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    f = client.post(
        f"/api/v1/intake/batches/{batch}/files",
        files={"file": ("long.pdf", pdf, "application/pdf")},
        headers={**w.headers, "Idempotency-Key": "m6-long"},
    )
    assert (
        process_document(app_engine, w.tenant_id, uuid.UUID(f.json()["id"]), LocalPdfExtractor())
        == "needs_review"
    )
    drain(app_engine)
    b = client.get(f"/api/v1/intake/batches/{batch}", headers=w.headers).json()
    assert b["totals"]["needs review"] == 1 and b["totals"]["ready"] == 0
    assert b["files"][0]["displayed_state"] == "needs review"
    q = client.get("/api/v1/exceptions", params={"status": "open"}, headers=w.headers).json()
    assert [i["type"] for i in q["items"]] == ["extraction_unverified"]  # the queue and the batch agree
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()
    assert any("review" in reason for reason in d["blocking"]), d["blocking"]
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 409


# --- m7 ---------------------------------------------------------------------------------------------


def test_m7_credit_recovered_refuses_another_suppliers_credit_note(app_engine, client):  # type: ignore[no-untyped-def]
    from .b14_helpers import second_supplier

    w = make_tenant(app_engine, "Fictional Distributor B14-m7")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "oct", "FF-1003", date(2026, 10, 6), "100", price="4.35")
    own = add_invoice(app_engine, w, "cn", "CN-OWN", date(2026, 10, 20), "1", doc_type="credit_note")
    w2 = second_supplier(app_engine, w)
    other = add_invoice(app_engine, w2, "cn2", "CN-77", date(2026, 10, 21), "1", doc_type="credit_note")
    match(client, app_engine, w.headers, [inv, own, other])
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    _op, oh = make_operator(app_engine)
    terms = {"price": "500.00", "period_start": "2026-10-01", "period_end": "2026-10-31"}
    assert (
        client.put(f"/api/v1/operator/tenants/{w.tenant_id}/pilot", json=terms, headers=oh).status_code == 200
    )
    assert (
        client.put("/api/v1/pilot/governing-report", json={"report_id": d["id"]}, headers=ctrl).status_code
        == 200
    )
    report = client.get(f"/api/v1/reports/backtest/{d['id']}", headers=ctrl).json()
    finding = next(
        f
        for f in report["findings"]
        if f["section"] == "finding" and f["snapshot"]["doc_number"] == "FF-1003"
    )
    url = f"/api/v1/reports/findings/{finding['id']}/outcomes"
    assert (
        client.post(
            url, json={"outcome": "controller_confirmed", "amount": finding["amount"]}, headers=ctrl
        ).status_code
        == 201
    )
    wrong = client.post(
        url,
        json={"outcome": "credit_recovered", "amount": "1.00", "credit_invoice_id": str(other)},
        headers=ctrl,
    )
    assert wrong.status_code == 422 and "another supplier" in wrong.text
    right = client.post(
        url,
        json={"outcome": "credit_recovered", "amount": "1.00", "credit_invoice_id": str(own)},
        headers=ctrl,
    )
    assert right.status_code == 201, right.text


# --- m8 ---------------------------------------------------------------------------------------------


def test_m8_the_calculation_names_tolerances_as_a_person_writes_them(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-m8")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "10", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "a", "INV-M8", date(2026, 10, 6), "10")
    match(client, app_engine, w.headers, [inv])
    assert (
        client.put(
            "/api/v1/tolerances/default", json={"price_tol_abs": "0.02", "price_tol_pct": "0.5"}, headers=ctrl
        ).status_code
        == 200
    )
    drain(app_engine)
    text_ = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["lines"][0]["match"][
        "calculation"
    ]
    assert "Quantity tolerance 0; price tolerance 0.02 or 0.5%." in text_, text_
    assert "0.0000" not in text_ and "0.020000" not in text_


# --- m9 ---------------------------------------------------------------------------------------------


def test_m9_invitations_one_per_address_never_for_a_member_and_the_audit_says_the_real_role(
    app_engine, client
):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-m9", role="controller")
    clerk_id, _clerk = add_user(app_engine, w, "clerk")
    with global_session(app_engine) as s:
        clerk_email = s.get(User, clerk_id).email  # type: ignore[union-attr]
    # An existing member is not invited; their role is changed under Users.
    r = client.post("/api/v1/invitations", json={"email": clerk_email, "role": "viewer"}, headers=w.headers)
    assert r.status_code == 409 and "already a member" in r.text
    # Repeats to one address never pile up.
    new = f"n.{uuid.uuid4().hex[:8]}@example.invalid"
    for role in ("viewer", "clerk", "clerk"):
        assert (
            client.post(
                "/api/v1/invitations", json={"email": new, "role": role}, headers=w.headers
            ).status_code
            == 201
        )
    open_ = client.get("/api/v1/invitations", headers=w.headers).json()["items"]
    assert [(i["email"], i["role"]) for i in open_] == [(new, "clerk")]


# --- m11 --------------------------------------------------------------------------------------------


def test_m11_a_line_is_not_removed_without_a_reason(app_engine, client):  # type: ignore[no-untyped-def]
    from decimal import Decimal as D

    from matchdesk.intake.models import InvoiceLineRow, InvoiceRow

    w = make_tenant(app_engine, "Fictional Distributor B14-m11")
    inv = add_invoice(app_engine, w, "a", "INV-M11", date(2026, 10, 6), "10")
    with session(w.tenant_id, app_engine) as s:
        extra = InvoiceLineRow(
            tenant_id=w.tenant_id,
            invoice_id=inv,
            line_no=2,
            supplier_item_code="W-100",
            qty=D("5"),
            uom="EA",
            unit_price=D("4.20"),
            amount=D("21.00"),
        )
        s.add(extra)
        s.get(InvoiceRow, inv).verification_status = "failed"  # type: ignore[union-attr]
        s.flush()
        extra_id = extra.id
    version = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]["version"]
    url = f"/api/v1/invoices/{inv}/lines/{extra_id}/removal"
    for body in ({}, {"reason": None}, {"reason": "   "}):
        r = client.post(url, json=body, headers={**w.headers, "If-Match": str(version)})
        assert r.status_code == 422 and "say why" in r.text
    with session(w.tenant_id, app_engine) as s:
        assert s.get(InvoiceLineRow, extra_id).removed_at is None  # type: ignore[union-attr]
    ok = client.post(
        url, json={"reason": "printed twice (synthetic)"}, headers={**w.headers, "If-Match": str(version)}
    )
    assert ok.status_code == 200, ok.text


# --- m12 --------------------------------------------------------------------------------------------


def test_m12_exports_write_json_and_explain_their_ids(app_engine, client):  # type: ignore[no-untyped-def]
    import csv
    import io
    import json
    import zipfile

    w = make_tenant(app_engine, "Fictional Distributor B14-m12")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_invoice(app_engine, w, "a", "INV-M12", date(2026, 10, 6), "10")
    assert (
        client.put("/api/v1/tolerances/default", json={"price_tol_abs": "0.03"}, headers=ctrl).status_code
        == 200
    )
    drain(app_engine)
    out = client.get("/api/v1/audit-events/export", headers=ctrl)
    assert out.status_code == 200
    rows = list(csv.DictReader(io.StringIO(out.text)))
    changed = next(r for r in rows if r["action"] == "tolerance.changed")
    from decimal import Decimal as D

    assert D(json.loads(changed["after"])["price_tol_abs"]) == D("0.03")  # JSON, not Python text
    assert "{'" not in out.text
    assert client.post("/api/v1/exports/archive", headers=ctrl).status_code == 202
    drain(app_engine)
    listed = client.get("/api/v1/exports/archive", headers=ctrl).json()["items"][0]
    z = zipfile.ZipFile(
        io.BytesIO(client.get(f"/api/v1/exports/archive/{listed['id']}/content", headers=ctrl).content)
    )
    names = set(z.namelist())
    assert {
        "suppliers.csv",
        "items.csv",
        "purchase_orders.csv",
        "purchase_order_lines.csv",
        "users.csv",
    } <= names
    suppliers = {r["id"]: r["name"] for r in csv.DictReader(io.StringIO(z.read("suppliers.csv").decode()))}
    invoice = next(csv.DictReader(io.StringIO(z.read("invoices.csv").decode())))
    assert suppliers[invoice["vendor_id"]] == "Fictional Supplier T"  # every id can be looked up
    users = list(csv.DictReader(io.StringIO(z.read("users.csv").decode())))
    assert {u["role"] for u in users} == {"clerk", "controller"} and all("@" not in u["name"] for u in users)
    audit = list(csv.DictReader(io.StringIO(z.read("audit_events.csv").decode())))
    assert all(json.loads(a["after"]) is not None for a in audit if a["after"])
    assert "users.csv" in z.read("README.txt").decode()
