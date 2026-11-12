"""B4: the read context the web app needs (S-08, S-09, S-11, S-12, S-17), the anti-forgery token on
``GET /me``, receiving file names, and the audit log endpoints. Rules are unchanged; these tests pin
that the added words and evidence agree with the stored result, that the QuickBooks billed
quantity is never part of "received to date", and that tenant isolation and roles still hold."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from matchdesk.api.app import create_app
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def matched_world(engine, client, name):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, name)
    add_receipt(engine, w, "60", date(2026, 10, 3), row=218)
    inv = add_invoice(engine, w, "a", "INV-01042", date(2026, 10, 5), "100")
    with session(w.tenant_id, engine) as s:  # QuickBooks says 100 billed: context only (AD-05)
        s.execute(text("update po_lines set qbo_billed_qty = 100"))
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    assert r.status_code in (200, 202), r.text
    drain(engine)
    return w, inv


def test_me_returns_the_sessions_anti_forgery_token(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B4-1")
    me = client.get("/api/v1/me", headers={"Cookie": w.headers["Cookie"]})
    assert me.status_code == 200
    assert me.json()["csrf_token"] == w.headers["X-CSRF-Token"]
    # The token from /me is accepted on a mutating request; a wrong one is refused.
    ok = client.post(
        "/api/v1/auth/session/extend",
        headers={"Cookie": w.headers["Cookie"], "X-CSRF-Token": me.json()["csrf_token"]},
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/v1/auth/session/extend", headers={"Cookie": w.headers["Cookie"], "X-CSRF-Token": "x" * 43}
    )
    assert bad.status_code == 403
    assert client.get("/api/v1/me").status_code == 401
    # The QuickBooks screen is told the mode, so recorded-response mode is labelled (B4).
    assert client.get("/api/v1/qbo/connection", headers=w.headers).json()["mode"] == "recorded"


def test_match_view_evidence_and_calculation(app_engine, client):  # type: ignore[no-untyped-def]
    w, inv = matched_world(app_engine, client, "Fictional Distributor B4-2")
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["vendor_name"] == "Fictional Supplier T" and body["po_number"] == "4471"
    line = body["lines"][0]
    assert line["supplier_item_code"] == "W-100" and line["qty"] == "100"
    m = line["match"]
    assert m["qty_received_cum"] == "60" and m["qty_invoiced_cum_net"] == "100"
    # The QuickBooks billed quantity is shown as context and never counted as received.
    assert line["purchase_order"]["qbo_billed_qty"] == "100"
    assert "Received to date 60 EA." in m["calculation"]
    assert "Excess 40 × 4.2 = 168.00." in m["calculation"]
    assert [r["source_row"] for r in line["receipts"]] == [218]
    assert line["receipts"][0]["counts"] is True and line["receipts"][0]["evidence_class"] == "A"
    exc = next(e for e in body["exceptions"] if e["type"] == "qty_over_received")
    assert exc["doc_number"] == "INV-01042" and exc["vendor_name"] == "Fictional Supplier T"
    assert exc["variance_amount"] == "168.00" and "waived" in exc["allowed_codes"]
    # The queue carries the same words and per-type counters.
    q = client.get("/api/v1/exceptions", params={"limit": 200}, headers=w.headers).json()
    row = next(e for e in q["items"] if e["id"] == exc["id"])
    assert row["po_number"] == "4471" and row["supplier_item_code"] == "W-100" and row["raised_at"]
    assert sum(q["type_counters"].values()) == len(q["items"])
    # Another tenant sees nothing (404, identical to a missing record).
    other = make_tenant(app_engine, "Fictional Distributor B4-3")
    assert client.get(f"/api/v1/invoices/{inv}", headers=other.headers).status_code == 404
    assert client.get("/api/v1/exceptions", headers=other.headers).json()["items"] == []


def test_receipt_absent_calculation_never_reads_as_received(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B4-4")
    inv = add_invoice(app_engine, w, "a", "INV-02001", date(2026, 10, 5), "10")
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update po_lines set qbo_billed_qty = 10"))
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    line = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["lines"][0]
    assert line["status"] == "exception" and line["match"]["receipt_line_count"] == 0
    assert "Received to date 0." in line["match"]["calculation"]
    assert line["receipts"] == []


def test_vendors_items_and_alias_context(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B4-5")
    vendors = client.get("/api/v1/vendors", headers=w.headers).json()["items"]
    assert [v["name"] for v in vendors] == ["Fictional Supplier T"]
    items = client.get("/api/v1/items", params={"q": "widget"}, headers=w.headers).json()["items"]
    assert [i["name"] for i in items] == ["Synthetic widget"]
    aliases = client.get("/api/v1/aliases", headers=w.headers).json()["items"]
    assert aliases[0]["vendor_name"] == "Fictional Supplier T"
    assert aliases[0]["item_name"] == "Synthetic widget" and aliases[0]["created_by_name"]


def test_audit_log_is_controller_only_paged_and_exported(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B4-6")  # a clerk
    _cid, ctrl = add_user(app_engine, w, "controller")
    for limit in ("110.00", "120.00", "130.00"):
        r = client.put(
            "/api/v1/tolerances/default",
            json={"waiver_limit": limit, "waiver_period_cap": "500.00"},
            headers=ctrl,
        )
        assert r.status_code == 200, r.text
    assert client.get("/api/v1/audit-events", headers=w.headers).status_code == 403
    first = client.get("/api/v1/audit-events", params={"limit": 2}, headers=ctrl).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    assert first["items"][0]["after"]["waiver_limit"] == "130.00"
    assert first["items"][0]["actor_name"] == "Synthetic controller"
    rest = client.get(
        "/api/v1/audit-events", params={"limit": 2, "cursor": first["next_cursor"]}, headers=ctrl
    ).json()
    ids = {e["id"] for e in first["items"]}
    assert rest["items"] and not ids & {e["id"] for e in rest["items"]}
    only = client.get("/api/v1/audit-events", params={"action": "waiver_limits"}, headers=ctrl).json()
    assert len(only["items"]) == 3
    csv_ = client.get("/api/v1/audit-events/export", params={"action": "waiver_limits"}, headers=ctrl)
    assert csv_.status_code == 200 and csv_.headers["content-type"].startswith("text/csv")
    assert csv_.text.splitlines()[0].startswith("occurred_at,actor,action")
    assert len(csv_.text.splitlines()) == 4
    other = make_tenant(app_engine, "Fictional Distributor B4-7", role="controller")
    assert client.get("/api/v1/audit-events", headers=other.headers).json()["items"] == []
    # There is no route that changes or deletes an audit event.
    assert client.delete("/api/v1/audit-events", headers=ctrl).status_code in (404, 405)


def test_receiving_import_keeps_the_file_name(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B4-8")
    data = b"PO,Line,Qty,Received\n4471,2,5,2026-10-01\n"
    r = client.post(
        "/api/v1/receiving/imports",
        headers=w.headers,
        files={"file": ("warehouse-log-oct.csv", data, "text/csv")},
        data={"evidence_class": "A"},
    )
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/v1/receiving/imports/{r.json()['id']}", headers=w.headers).json()
    assert detail["preview"]["headers"] == ["PO", "Line", "Qty", "Received"]
    assert detail["preview"]["sample_rows"] == [["4471", "2", "5", "2026-10-01"]]
    listed = client.get("/api/v1/receiving/imports", headers=w.headers).json()["items"]
    assert listed[0]["file_name"] == "warehouse-log-oct.csv" and listed[0]["created_at"]
    again = client.post(
        "/api/v1/receiving/imports",
        headers=w.headers,
        files={"file": ("copy.csv", data, "text/csv")},
        data={"evidence_class": "A"},
    )
    assert again.status_code in (201, 409)  # a draft is not live yet; a committed file would be 409


def test_identical_files_uploaded_at_once_become_one_document_and_a_duplicate(app_engine, client):  # type: ignore[no-untyped-def]
    from concurrent.futures import ThreadPoolExecutor

    w = make_tenant(app_engine, "Fictional Distributor B4-9")
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    data = b"%PDF-1.4\n% synthetic identical upload B4-9\n%%EOF\n"

    def put(n: int) -> int:
        r = client.post(
            f"/api/v1/intake/batches/{batch}/files",
            headers={**w.headers, "Idempotency-Key": f"race-{n}"},
            files={"file": (f"copy-{n}.pdf", data, "application/pdf")},
        )
        return r.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(put, range(4)))
    assert codes == [201, 201, 201, 201]
    files = client.get(f"/api/v1/intake/batches/{batch}", headers=w.headers).json()["files"]
    states = sorted(f["state"] for f in files)
    assert len(files) == 4 and states.count("duplicate_file") == 3
