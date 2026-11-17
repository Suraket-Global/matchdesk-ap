"""B15 (2026-11-17): the bugs found while recording the product tour. All data synthetic.

- Bug 4: voiding a receiving import closes its pending late-receiving approval (withdrawn, with an
  audit entry) so the report can be approved; nothing is approved by it.
- Bug 5: an account in USD matches its USD invoices (the run took "CAD" for every account), and
  ``/me``, the weekly email and the report PDF carry the account's currency.
- Bug 1 (server half): a draft save answers the new version, and Confirm with that version works.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.audit.models import AuditEvent
from matchdesk.exceptions.models import Approval
from matchdesk.reporting import blocking_reasons
from matchdesk.reporting.weekly import email_text, summary
from matchdesk.tenancy import global_session, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, attest, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def _late_import(client, w) -> dict:  # type: ignore[no-untyped-def]
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("late.csv", b"PO,Line,Qty,Received\n4471,2,50,2026-10-02\n")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    client.put(
        f"/api/v1/receiving/imports/{up['id']}/mapping",
        headers=w.headers,
        json={
            "columns": {
                "po_number": "PO",
                "line_no": "Line",
                "qty_received": "Qty",
                "received_date": "Received",
            }
        },
    )
    c = client.post(f"/api/v1/receiving/imports/{up['id']}/commit", headers=w.headers).json()
    assert c["late_lines"] == 1 and c["late_approval_id"], c
    return c


def test_bug4_voiding_an_import_closes_its_pending_late_approval(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B15-4")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "50", date(2026, 10, 1))
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "inv", "INV-B15-4", date(2026, 10, 5), "100")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    c = _late_import(client, w)
    drain(app_engine)
    with session(w.tenant_id, app_engine) as s:
        assert any(
            "approval(s) pending" in r for r in blocking_reasons(s, date(2026, 10, 1), date(2026, 10, 31))
        )
    v = client.post(
        f"/api/v1/receiving/imports/{c['id']}/void",
        json={"reason": "Loaded the wrong file"},
        headers=w.headers,
    )
    assert v.status_code == 200, v.text
    drain(app_engine)
    with session(w.tenant_id, app_engine) as s:
        ap = s.get(Approval, c["late_approval_id"])
        assert ap is not None and ap.status == "withdrawn"  # closed, never approved
        assert ap.decided_by is None and "voided" in (ap.decision_note or "")
        audit = s.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == ap.id, AuditEvent.action == "approval.withdrawn")
        ).all()
        assert len(audit) == 1 and audit[0].after["reason"] == "import_voided"
        late = (
            s.execute(
                text("select late_approved from receipt_lines where receiving_import_id = :i"), {"i": c["id"]}
            )
            .scalars()
            .all()
        )
        assert late and not any(late)  # the voided late lines were not approved
        assert not any(
            "approval(s) pending" in r for r in blocking_reasons(s, date(2026, 10, 1), date(2026, 10, 31))
        )
    # The closed approval cannot be decided afterwards.
    d = client.post(
        f"/api/v1/approvals/{c['late_approval_id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(ap.version)},
    )
    assert d.status_code == 409


def test_bug4_an_approval_of_an_import_voided_earlier_is_closed_and_cannot_be_approved(app_engine, client):  # type: ignore[no-untyped-def]
    """The state the tour left behind: an import voided before B15, its approval still pending."""
    w = make_tenant(app_engine, "Fictional Distributor B15-4b")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "50", date(2026, 10, 1))
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "inv", "INV-B15-4B", date(2026, 10, 5), "100")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    c = _late_import(client, w)
    with session(w.tenant_id, app_engine) as s:  # voided the old way: the approval left pending
        s.execute(
            text("update receiving_imports set state = 'voided', voided_at = now() where id = :i"),
            {"i": c["id"]},
        )
    ap = client.get("/api/v1/approvals", params={"subject_type": "late_receipt"}, headers=ctrl).json()[
        "items"
    ][0]
    d = client.post(
        f"/api/v1/approvals/{ap['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(ap["version"])},
    )
    assert d.status_code == 409  # never approves late lines of a voided import
    v = client.post(
        f"/api/v1/receiving/imports/{c['id']}/void", json={"reason": "Close what is left"}, headers=w.headers
    )
    assert v.status_code == 200, v.text
    with session(w.tenant_id, app_engine) as s:
        assert s.get(Approval, ap["id"]).status == "withdrawn"  # type: ignore[union-attr]


def _usd(engine, w) -> None:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        s.execute(text("update tenants set currency = 'USD' where id = :t"), {"t": w.tenant_id})
    with session(w.tenant_id, engine) as s:
        s.execute(text("update invoices set currency = 'USD'"))


def test_bug5_a_usd_account_matches_its_usd_invoices(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B15-5")
    add_receipt(app_engine, w, "10", date(2026, 10, 1))
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "inv", "INV-B15-5", date(2026, 10, 5), "10")
    _usd(app_engine, w)
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    assert r.status_code in (200, 202), r.text
    drain(app_engine)
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] == "matched", body
    types = {
        e["type"]
        for e in client.get("/api/v1/exceptions", params={"limit": 200}, headers=w.headers).json()["items"]
    }
    assert "currency_unsupported" not in types
    me = client.get("/api/v1/me", headers=w.headers).json()
    assert me["currency"] == "USD"


def test_bug5_weekly_email_and_report_pdf_name_the_account_currency(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B15-5b", role="controller")
    add_receipt(app_engine, w, "10", date(2026, 10, 1))
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "inv", "INV-B15-5B", date(2026, 10, 5), "12")
    _usd(app_engine, w)
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    with session(w.tenant_id, app_engine) as s:
        fig = summary(s, date(2026, 10, 5))
    assert fig["currency"] == "USD"
    _subject, text_body = email_text("Fictional Distributor B15-5b", fig, "http://localhost/x")
    assert "USD" in text_body and "CAD" not in text_body
    d = client.post(
        "/api/v1/reports/backtest",
        json={"period_start": "2026-10-01", "period_end": "2026-10-31"},
        headers=w.headers,
    )
    assert d.status_code in (200, 201), d.text
    pdf = client.get(
        f"/api/v1/reports/backtest/{d.json()['id']}/export", params={"format": "pdf"}, headers=w.headers
    )
    assert pdf.status_code == 200
    assert (
        b"Totals \\(USD\\)" in pdf.content and b"Totals \\(CAD\\)" not in pdf.content
    )  # PDF escapes parentheses


def test_bug1_draft_save_answers_the_new_version_and_confirm_takes_it(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B15-1")
    inv = add_invoice(app_engine, w, "inv", "INV-B15-1", date(2026, 10, 5), "10")
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update invoices set verification_status = 'failed'"))
        s.execute(text("update documents set state = 'needs_review'"))
    rv = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]
    fields = {**rv["fields"], "doc_number": "INV-B15-1A"}
    lines = [
        {
            k: ln[k]
            for k in (
                "line_no",
                "supplier_item_code",
                "description",
                "qty",
                "uom",
                "unit_price",
                "amount",
                "line_kind",
            )
        }
        for ln in rv["line_fields"]
    ]
    saved = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"draft": True, "fields": fields, "lines": lines},
        headers={**w.headers, "If-Match": str(rv["version"])},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == rv["version"] + 1
    assert saved.json()["review_draft"]["fields"]["doc_number"] == "INV-B15-1A"
    # The old version is refused (what the client sent before the fix); the new one is accepted.
    stale = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"draft": False, "fields": fields, "lines": lines},
        headers={**w.headers, "If-Match": str(rv["version"])},
    )
    assert stale.status_code == 409
    final = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"draft": False, "fields": fields, "lines": lines},
        headers={**w.headers, "If-Match": str(saved.json()["version"])},
    )
    assert final.status_code == 200, final.text
    ok = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction",
        json={"accept_inconsistent": False},
        headers={**w.headers, "If-Match": str(final.json()["version"])},
    )
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["doc_number"] == "INV-B15-1A"
