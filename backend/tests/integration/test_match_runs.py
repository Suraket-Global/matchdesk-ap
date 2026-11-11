"""Match runs through the database: API, job, worker, supersede, reconciliation (T-4.1.6; IT-15 partial; IT-16)."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from matchdesk.api.app import create_app
from matchdesk.core import configure_logging
from matchdesk.qbo.models import QboBillLineRow, QboBillRow
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import NOW, add_invoice, add_receipt, make_tenant

pytestmark = pytest.mark.integration


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def test_golden_flow_supersede_and_credit(app_engine):  # type: ignore[no-untyped-def]
    log_stream = io.StringIO()
    configure_logging("INFO", log_stream)
    w = make_tenant(app_engine, "Fictional Distributor A")
    add_invoice(app_engine, w, "inv", "INV-01042", date(2026, 10, 4), "100")
    add_receipt(app_engine, w, "60", date(2026, 10, 3))
    client = TestClient(create_app())
    h = {
        **w.headers,
        "Idempotency-Key": "k-1",
        "X-Correlation-Id": "00000000-0000-4000-8000-000000000001",
    }
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["inv"])]}, headers=h)
    assert r.status_code == 202, r.text
    run1 = r.json()["id"]
    # Same key, same request: the stored result of the first attempt.
    again = client.post("/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["inv"])]}, headers=h)
    assert again.json()["id"] == run1
    clash = client.post(
        "/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["inv"]), str(w.po_id)]}, headers=h
    )
    assert clash.status_code in (404, 409)
    drain(app_engine)
    body = client.get(f"/api/v1/match-runs/{run1}", headers=h).json()
    assert body["state"] == "succeeded" and body["lines_evaluated"] == 1 and body["lines_matched"] == 0
    inv = client.get(f"/api/v1/invoices/{w.invoices['inv']}", headers=h).json()
    [exc] = inv["exceptions"]
    assert (exc["type"], exc["variance_amount"], exc["status"], exc["qualifying"]) == (
        "qty_over_received",
        "168.00",
        "open",
        True,
    )
    # Unchanged inputs: no new run, the earlier one is returned.
    same = client.post(
        "/api/v1/match-runs",
        json={"invoice_ids": [str(w.invoices["inv"])]},
        headers=w.headers,
    )
    assert same.status_code == 200 and same.json()["id"] == run1

    # A credit note arrives: a new run supersedes the result and the exception is resolved by credit.
    cn = add_invoice(
        app_engine,
        w,
        "cn",
        "CN-0031",
        date(2026, 10, 20),
        "40",
        doc_type="credit_note",
        references="INV-01042",
    )
    r2 = client.post(
        "/api/v1/match-runs",
        json={"invoice_ids": [str(w.invoices["inv"]), str(cn)]},
        headers=w.headers,
    )
    assert r2.status_code == 202
    drain(app_engine)
    inv2 = client.get(f"/api/v1/invoices/{w.invoices['inv']}", headers=h).json()
    assert inv2["lines"][0]["status"] == "matched"
    [exc2] = inv2["exceptions"]
    assert exc2["id"] == exc["id"]  # same row, kept by fingerprint
    assert (exc2["status"], exc2["resolution_code"], exc2["reported_amount"]) == (
        "resolved",
        "resolved_by_credit",
        "0.00",
    )
    with session(w.tenant_id, app_engine) as s:
        rows = s.execute(
            text(
                "select is_current, status from line_matches where invoice_line_id = "
                "(select id from invoice_lines where invoice_id = :i) order by created_at"
            ),
            {"i": str(w.invoices["inv"])},
        ).all()
        assert [tuple(r) for r in rows] == [(False, "exception"), (True, "matched")]
        events = [r[0] for r in s.execute(text("select event from exception_events order by created_at"))]
        assert events == ["raised", "resolved"]
        audit = s.execute(
            text("select count(*) from audit_events where action = 'match_run.stored'")
        ).scalar()
        assert audit == 2

    # IT-16 (partial): no fixture price or document number in any log line; correlation ID reused by the job.
    logs = log_stream.getvalue()
    for secret in ("4.20", "168.00", "INV-01042", w.token):
        assert secret not in logs
    assert logs.count("00000000-0000-4000-8000-000000000001") >= 2
    configure_logging("INFO")


def test_ut12_qbo_bill_history_through_database(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "History tenant")
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update po_lines set qbo_billed_qty = 100 where id = :p"), {"p": str(w.po_line_id)})
        bill = QboBillRow(
            tenant_id=w.tenant_id,
            qbo_id="B980",
            txn_type="bill",
            vendor_id=w.vendor_id,
            doc_number="INV-00980",
            doc_number_norm="INV980",
            txn_date=date(2026, 9, 15),
            total=D("420.00"),
            synced_at=NOW,
        )
        s.add(bill)
        s.flush()
        s.add(
            QboBillLineRow(
                tenant_id=w.tenant_id,
                qbo_bill_id=bill.id,
                qty=D("100"),
                amount=D("420.00"),
                po_line_id=w.po_line_id,
            )
        )
    add_invoice(app_engine, w, "oct", "INV-01042", date(2026, 10, 8), "100")
    add_receipt(app_engine, w, "100", date(2026, 10, 6))
    client = TestClient(create_app())
    h = w.headers
    assert (
        client.post(
            "/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h
        ).status_code
        == 202
    )
    drain(app_engine)
    inv = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert inv["lines"][0]["status"] == "exception"
    by_type = {e["type"]: e for e in inv["exceptions"]}
    assert set(by_type) == {
        "qty_over_received",
        "qty_over_ordered",
    }  # 200 invoiced vs 100 received and ordered
    exc = by_type["qty_over_received"]
    assert (exc["variance_qty"], exc["variance_amount"], exc["reported_amount"]) == (
        "100.0000",
        "420.00",
        "420.00",
    )
    assert by_type["qty_over_ordered"]["reported_amount"] == "0.00"  # one amount reported, never both


def test_viewer_cannot_start_a_run(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Viewer tenant", role="viewer")
    add_invoice(app_engine, w, "inv", "INV-1", date(2026, 10, 4), "1")
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/match-runs",
        json={"invoice_ids": [str(w.invoices["inv"])]},
        headers=w.headers,
    )
    assert r.status_code == 403
