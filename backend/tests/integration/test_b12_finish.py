"""B12 (2026-11-13): deleting one document, and the controller's usage. All data synthetic.

1. A document no one accepted yet: a clerk deletes it without a reason (soft, audited, file kept).
2. A document accepted into matching: controller only, with a reason; its results are retired, its
   exceptions closed with ``document_removed``, and the supplier's other documents re-matched without
   it (a duplicate that used it is decided again).
3. A document in an approved report stays in that report; a later draft lists it as deleted after
   approval.
4. Refusals: still being read, already deleted, not an invoice document.
5. ``GET /usage``: controller only, the operator's figures by month without a price.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk import blobstore, reporting
from matchdesk.api.app import create_app
from matchdesk.exceptions.models import Approval, ExceptionEvent, ExceptionRow, LineMatch, MatchRun
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow, UploadBatch, UsageEvent
from matchdesk.reporting.models import BacktestReport, ReportFinding
from matchdesk.tenancy import operator_session, session
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
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(i) for i in ids]}, headers=headers)
    assert r.status_code in (200, 202), r.text
    drain(engine)


def excs(engine, w, invoice_id) -> list[ExceptionRow]:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        return list(s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id == invoice_id)).all())


def actions(engine, tenant_id) -> list[str]:  # type: ignore[no-untyped-def]
    with session(tenant_id, engine) as s:
        return [r[0] for r in s.execute(text("select action from audit_events order by occurred_at")).all()]


def delete(client, doc_id, headers, reason=None):  # type: ignore[no-untyped-def]
    body = {"reason": reason} if reason is not None else {}
    return client.post(f"/api/v1/documents/{doc_id}/deletion-requests", json=body, headers=headers)


def test_clerk_deletes_a_document_not_yet_accepted_soft_and_audited(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B12-R1")
    inv = add_invoice(app_engine, w, "r1", "INV-B12R1", date(2026, 10, 6), "10")
    doc_id = w.documents["r1"]
    with session(w.tenant_id, app_engine) as s:
        s.get(InvoiceRow, inv).verification_status = "failed"  # type: ignore[union-attr]
        batch = UploadBatch(tenant_id=w.tenant_id, file_count=1)
        s.add(batch)
        s.flush()
        batch_id = batch.id
        doc_row = s.get(DocumentRow, doc_id)
        assert doc_row is not None
        doc_row.state, doc_row.batch_id = "needs_review", batch_id
    rule = client.get(f"/api/v1/documents/{doc_id}/deletion", headers=w.headers).json()
    assert rule == {
        "accepted": False,
        "needs_controller": False,
        "reason_required": False,
        "blocked": None,
        "removed_at": None,
        "removed_reason": None,
    }
    r = delete(client, doc_id, w.headers)
    assert r.status_code == 200, r.text
    assert r.json()["invoice_ids"] == [str(inv)] and r.json()["reason"] is None
    with session(w.tenant_id, app_engine) as s:
        doc = s.get(DocumentRow, doc_id)
        assert doc is not None and doc.removed_at is not None and doc.removed_by == w.user_id
        assert doc.deleted_at is None  # the original file stays until retention removes it
        assert blobstore.get(w.tenant_id, doc.blob_key)
        assert s.get(InvoiceRow, inv) is not None  # the row stays as history
    # Lists hide it; the document itself says it was deleted, and nothing is pending on it.
    listed = client.get("/api/v1/invoices", headers=w.headers).json()["items"]
    assert str(inv) not in {i["id"] for i in listed}
    detail = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert detail["removed"]["removed_by_name"] == "Synthetic user" and detail["stale"] is False
    assert "document.removed" in actions(app_engine, w.tenant_id)
    # The batch counts it once, as deleted, so its counts still add up to the file count.
    b = client.get(f"/api/v1/intake/batches/{batch_id}", headers=w.headers).json()
    assert b["totals"]["deleted"] == 1 and b["totals"]["needs review"] == 0
    assert sum(v for k, v in b["totals"].items() if k != "file_count") == b["totals"]["file_count"] == 1
    assert b["files"][0]["displayed_state"] == "deleted" and b["files"][0]["removed_at"]
    # A second deletion is refused.
    assert delete(client, doc_id, w.headers).status_code == 409


def test_accepted_document_needs_the_controller_and_a_reason_and_rematches_the_rest(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B12-D1")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "INV-B12D1", date(2026, 10, 2), "10")
    b = add_invoice(app_engine, w, "b", "INV-B12D1", date(2026, 10, 9), "10")  # the same invoice again
    match(client, app_engine, w.headers, [a, b])
    dup_on = {inv: [e for e in excs(app_engine, w, inv) if e.type == "duplicate"] for inv in (a, b)}
    second = a if dup_on[a] else b
    first = b if second == a else a
    assert dup_on[second] and dup_on[second][0].status == "open"
    key = "a" if second == a else "b"
    doc_id = w.documents[key]
    with session(w.tenant_id, app_engine) as s:
        lines = list(s.scalars(select(InvoiceLineRow.id).where(InvoiceLineRow.invoice_id == second)).all())
        dup = dup_on[second][0]
        s.add(
            Approval(
                tenant_id=w.tenant_id,
                subject_type="waiver",
                exception_id=dup.id,
                amount=dup.reported_amount or dup.variance_amount,
                requested_by=w.user_id,
                status="pending",
            )
        )
    rule = client.get(f"/api/v1/documents/{doc_id}/deletion", headers=w.headers).json()
    assert rule["accepted"] and rule["needs_controller"] and rule["reason_required"]
    assert delete(client, doc_id, w.headers, "Uploaded twice (synthetic)").status_code == 403  # clerk
    assert delete(client, doc_id, ctrl).status_code == 422  # no reason
    assert delete(client, doc_id, ctrl, "   ").status_code == 422
    r = delete(client, doc_id, ctrl, "Uploaded twice by mistake (synthetic)")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["exceptions_closed"] >= 1 and body["approvals_withdrawn"] == 1 and body["match_run_id"]
    with session(w.tenant_id, app_engine) as s:
        run = s.get(MatchRun, uuid.UUID(body["match_run_id"]))
        assert (
            run is not None
            and run.trigger == "document_removed"
            and str(second) not in run.scope["invoice_ids"]
        )
        # History kept, no current result on the deleted lines.
        assert s.scalar(select(LineMatch.id).where(LineMatch.invoice_line_id.in_(lines))) is not None
        assert (
            s.scalar(
                select(LineMatch.id).where(
                    LineMatch.invoice_line_id.in_(lines), LineMatch.is_current.is_(True)
                )
            )
            is None
        )
        ev = s.scalars(
            select(ExceptionEvent).where(
                ExceptionEvent.exception_id == dup.id, ExceptionEvent.event == "document_removed"
            )
        ).one()
        assert ev.actor_user_id is not None and ev.detail["reason"].startswith("Uploaded twice")
        assert s.scalar(select(Approval.status).where(Approval.exception_id == dup.id)) == "withdrawn"
    assert all(e.status == "auto_closed" for e in excs(app_engine, w, second))
    drain(app_engine)
    # The remaining invoice is matched again without the deleted one: no duplicate left anywhere.
    assert not [e for e in excs(app_engine, w, first) if e.type == "duplicate" and e.status != "auto_closed"]
    detail = client.get(f"/api/v1/invoices/{first}", headers=w.headers).json()
    assert detail["stale"] is False and detail["lines"][0]["status"] == "matched"
    # The same file can be uploaded again once deleted (the unique index skips deleted documents).
    with session(w.tenant_id, app_engine) as s:
        old = s.get(DocumentRow, doc_id)
        assert old is not None
        again = DocumentRow(
            tenant_id=w.tenant_id,
            purpose="invoice",
            source="upload",
            blob_key=f"t/{w.tenant_id}/again/{uuid.uuid4()}",
            sha256=old.sha256,
            mime_type="application/pdf",
            byte_size=old.byte_size,
            state="queued",
            correlation_id=uuid.uuid4(),
        )
        s.add(again)
        s.flush()


def test_approved_report_keeps_the_document_and_a_later_draft_lists_it(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B12-A1")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "INV-B12A1", date(2026, 10, 6), "50", price="4.35")  # 7.50 over
    b = add_invoice(app_engine, w, "b", "INV-B12A2", date(2026, 10, 20), "20", price="4.35")  # 3.00 over
    match(client, app_engine, w.headers, [a, b])
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    with session(w.tenant_id, app_engine) as s:
        frozen = sorted((f.exception_id, f.amount) for f in s.scalars(select(ReportFinding)))
    # A draft with no change is refused (B6 review M6); after the deletion one is offered.
    r = delete(client, w.documents["b"], ctrl, "Belongs to another account (synthetic)")
    assert r.status_code == 200, r.text
    drain(app_engine)
    with session(w.tenant_id, app_engine) as s:
        approved = s.get(BacktestReport, uuid.UUID(d["id"]))
        assert approved is not None and approved.status == "approved"
        assert approved.totals["documents"] == 2  # immutable: still the version that was approved
        assert sorted(
            (f.exception_id, f.amount)
            for f in s.scalars(select(ReportFinding).where(ReportFinding.report_id == approved.id))
        ) == [x for x in frozen]
    later = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers)
    assert later.status_code in (200, 201), later.text
    totals = later.json()["totals"]
    assert totals["documents"] == 1
    gone = totals["deleted_after_approval"]
    assert [g["doc_number"] for g in gone] == ["INV-B12A2"] and gone[0]["approved_versions"] == [1]
    assert gone[0]["reason"].startswith("Belongs to another")
    pdf = client.get(f"/api/v1/reports/backtest/{later.json()['id']}/export?format=pdf", headers=w.headers)
    assert pdf.status_code == 200


def test_refusals_while_reading_and_for_other_files(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B12-X1")
    add_invoice(app_engine, w, "x", "INV-B12X1", date(2026, 10, 6), "10")
    doc_id = w.documents["x"]
    with session(w.tenant_id, app_engine) as s:
        s.get(DocumentRow, doc_id).state = "running"  # type: ignore[union-attr]
    r = delete(client, doc_id, w.headers)
    assert r.status_code == 409 and "still being read" in r.text
    assert client.get(f"/api/v1/documents/{doc_id}/deletion", headers=w.headers).json()["blocked"]
    assert delete(client, uuid.uuid4(), w.headers).status_code == 404
    other = make_tenant(app_engine, "Fictional Distributor B12-X2")
    assert delete(client, doc_id, other.headers).status_code == 404  # another account's document
    _v, viewer = add_user(app_engine, w, "viewer")
    assert delete(client, doc_id, viewer).status_code == 403


def test_usage_is_the_operator_figure_for_the_controller_only(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B12-U1")
    _c, ctrl = add_user(app_engine, w, "controller")
    a = add_invoice(app_engine, w, "a", "INV-B12U1", date(2026, 9, 6), "10")
    b = add_invoice(app_engine, w, "b", "INV-B12U2", date(2026, 10, 6), "10")
    c = add_invoice(app_engine, w, "c", "CN-B12U3", date(2026, 10, 9), "2", doc_type="credit_note")
    with session(w.tenant_id, app_engine) as s:
        for inv, key, month, kind in (
            (a, "a", date(2026, 9, 1), "invoice"),
            (b, "b", date(2026, 10, 1), "invoice"),
            (c, "c", date(2026, 10, 1), "credit_note"),
        ):
            s.add(
                UsageEvent(
                    tenant_id=w.tenant_id,
                    invoice_id=inv,
                    document_id=w.documents[key],
                    unit_month=month,
                    kind=kind,
                )
            )
    assert client.get("/api/v1/usage", headers=w.headers).status_code == 403  # clerk
    r = client.get("/api/v1/usage", headers=ctrl)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == [
        {"month": "2026-09-01", "invoice": 1, "credit_note": 0, "units": 1},
        {"month": "2026-10-01", "invoice": 1, "credit_note": 1, "units": 2},
    ]
    assert body["total_units"] == 3 and "price" not in str(body)
    with operator_session(app_engine) as s:
        assert reporting.usage_by_month(s, w.tenant_id) == body["items"]  # what S-18 shows
    # A deleted document stays billed: it was read.
    assert delete(client, w.documents["b"], ctrl, "Wrong file (synthetic)").status_code == 200
    assert client.get("/api/v1/usage", headers=ctrl).json()["total_units"] == 3
