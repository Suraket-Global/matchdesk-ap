"""B3 back-test report: T-5.1.1 (totals equal queries on report_findings), T-5.1.2 (blocking checks,
immutable versions, export with the draft mark, UT-11), IT-17 cases (a) to (e) on stored reports."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from matchdesk.api.app import create_app
from matchdesk.reporting.models import ReportFinding
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, make_tenant

pytestmark = pytest.mark.integration
OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def match(client, engine, headers, ids) -> None:  # type: ignore[no-untyped-def]
    assert client.post(
        "/api/v1/match-runs", json={"invoice_ids": [str(i) for i in ids]}, headers=headers
    ).status_code in (200, 202)
    drain(engine)


def test_report_totals_approval_versions_refund_and_export(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor P1")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "oct", "INV-P1", date(2026, 10, 6), "100", price="4.35")
    later = add_invoice(app_engine, w, "nov", "INV-P2", date(2026, 11, 3), "1", price="4.20")
    match(client, app_engine, w.headers, [inv, later])
    d1 = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers)
    assert d1.status_code == 201, d1.text
    r1 = d1.json()
    assert r1["status"] == "draft" and r1["draft_mark"] == "DRAFT - NOT APPROVED"
    assert r1["findings_amount"] == "15.00" and r1["qualifying_amount"] == "15.00" and r1["blocking"] == []
    assert r1["totals"]["documents"] == 1  # the November invoice is outside the period
    with session(w.tenant_id, app_engine) as s:  # totals equal queries on report_findings
        q = s.scalar(
            select(func.sum(ReportFinding.amount)).where(
                ReportFinding.report_id == r1["id"], ReportFinding.section == "finding"
            )
        )
        assert q == Decimal("15.00")
    assert client.post(f"/api/v1/reports/backtest/{r1['id']}/approve", headers=w.headers).status_code == 403
    pdf = client.get(f"/api/v1/reports/backtest/{r1['id']}/export?format=pdf", headers=w.headers)
    assert (
        pdf.status_code == 200 and pdf.content.startswith(b"%PDF-") and b"DRAFT - NOT APPROVED" in pdf.content
    )
    ok = client.post(f"/api/v1/reports/backtest/{r1['id']}/approve", headers=ctrl)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    again = client.post(f"/api/v1/reports/backtest/{r1['id']}/approve", headers=ctrl)
    assert again.status_code == 200  # idempotent
    approved_pdf = client.get(f"/api/v1/reports/backtest/{r1['id']}/export?format=pdf", headers=w.headers)
    assert b"DRAFT - NOT APPROVED" not in approved_pdf.content
    # IT-17 (a)/(b) on a stored report: refund due only below the threshold.
    ev = client.get(f"/api/v1/reports/backtest/{r1['id']}/refund-evaluation", headers=w.headers).json()
    assert ev["qualifying_total"] == "15.00" and ev["refund_due"] is True
    ev10 = client.get(
        f"/api/v1/reports/backtest/{r1['id']}/refund-evaluation?threshold=10.00", headers=w.headers
    )
    assert ev10.json()["threshold"] == "500.00"  # the caller cannot choose it (review M6)
    # IT-17 (e): the controller waives the finding; a new version still counts it.
    pv = client.get("/api/v1/exceptions", params={"type": "price_variance"}, headers=w.headers).json()[
        "items"
    ][0]
    wv = client.post(
        f"/api/v1/exceptions/{pv['id']}/resolutions",
        json={"code": "waived", "note": "synthetic"},
        headers={**ctrl, "If-Match": str(pv["version"])},
    )
    assert wv.json()["result"] == "waived"
    r2 = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert r2["version_no"] == 2 and r2["qualifying_amount"] == "15.00"
    assert r2["totals"]["sections"]["waived"]["amount"] == "15.00" and r2["findings_amount"] == "0.00"
    # IT-17 (d): approving version 2 supersedes version 1, whose stored result does not change.
    assert client.post(f"/api/v1/reports/backtest/{r2['id']}/approve", headers=ctrl).status_code == 200
    v1 = client.get(f"/api/v1/reports/backtest/{r1['id']}", headers=w.headers).json()
    assert v1["status"] == "superseded" and v1["qualifying_amount"] == "15.00"
    # A superseded version is not the governing report (review M6).
    assert (
        client.get(f"/api/v1/reports/backtest/{r1['id']}/refund-evaluation", headers=w.headers).status_code
        == 409
    )
    with pytest.raises(DBAPIError, match="immutable"), session(w.tenant_id, app_engine) as s:
        s.execute(text("update backtest_reports set qualifying_amount = 0 where id = :i"), {"i": r1["id"]})
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
        s.execute(text("delete from report_findings where report_id = :i"), {"i": r1["id"]})


def test_it17c_no_receiving_evidence_reports_finding_and_unverified(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor P2")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "inv", "INV-C1", date(2026, 10, 9), "60", price="4.35")
    match(client, app_engine, w.headers, [inv])
    r = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    # TRD 8.5 worked example: finding 9.00, unverified 261.00 - 9.00 = 252.00.
    assert r["findings_amount"] == "9.00" and r["unverified_amount"] == "252.00"
    assert r["qualifying_amount"] == "9.00" and r["receipt_coverage_pct"] == "0.00"
    assert client.post(f"/api/v1/reports/backtest/{r['id']}/approve", headers=ctrl).status_code == 200
    ev = client.get(f"/api/v1/reports/backtest/{r['id']}/refund-evaluation", headers=w.headers).json()
    assert ev["refund_due"] is True and ev["unverified_total"] == "252.00"


def test_blocking_checks_stale_and_csv_formula_guard(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor P3")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 10, 1))
    inv = add_invoice(app_engine, w, "inv", "INV-B1", date(2026, 10, 9), "100")
    unmatched = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert any("not matched" in b for b in unmatched["blocking"])
    assert client.post(f"/api/v1/reports/backtest/{unmatched['id']}/approve", headers=ctrl).status_code == 409
    match(client, app_engine, w.headers, [inv])
    r = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert r["blocking"] == []
    add_receipt(app_engine, w, "5", date(2026, 10, 2), row=2)  # inputs change: results are stale on read
    refused = client.post(f"/api/v1/reports/backtest/{r['id']}/approve", headers=ctrl)
    assert refused.status_code == 409 and "out of date" in refused.json()["detail"]
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update vendors set name = :n"), {"n": '=HYPERLINK("http://example.invalid")'})
    add_invoice(app_engine, w, "x", "INV-B2", date(2026, 10, 12), "100", price="4.50")
    drain(app_engine)
    ids = [i["id"] for i in client.get("/api/v1/invoices", headers=w.headers).json()["items"]]
    match(client, app_engine, w.headers, ids)
    r3 = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    csv_bytes = client.get(
        f"/api/v1/reports/backtest/{r3['id']}/export?format=csv", headers=w.headers
    ).content
    assert csv_bytes.startswith(b"DRAFT - NOT APPROVED")
    assert b"'=HYPERLINK" in csv_bytes and b",=HYPERLINK" not in csv_bytes
