"""B3 invoice intake with the local text-PDF reader, extraction review and re-entry into matching:
T-3.3.1 to T-3.3.3; IT-14 for documents; a false-pass guard (a document that failed the gates is
never matched, whatever the receipts say)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from matchdesk.api.app import create_app
from matchdesk.core import text_pdf
from matchdesk.extraction.local_pdf import LocalPdfExtractor
from matchdesk.intake import process_document
from matchdesk.intake.models import InvoiceRow
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_receipt, make_tenant

pytestmark = pytest.mark.integration


def invoice_pdf(
    number: str, qty: str = "100", total: str = "420.00", vendor: str = "Fictional Supplier T"
) -> bytes:
    amount = f"{int(qty) * 4.20:.2f}" if qty.isdigit() else "0.00"
    return text_pdf(
        [
            "INVOICE",
            f"Vendor: {vendor}",
            f"Invoice No: {number}",
            "Invoice Date: 2026-10-10",
            "PO Number: 4471",
            "Currency: CAD",
            f"W-100   Synthetic widget   {qty}  EA   4.20   {amount}",
            f"Subtotal: {amount}",
            "Tax: 0.00",
            f"Total: {total}",
        ]
    )


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def upload_and_process(client, app_engine, w, data: bytes, key: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    r = client.post(
        f"/api/v1/intake/batches/{batch}/files",
        files={"file": ("inv.pdf", data, "application/pdf")},
        headers={**w.headers, "Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    doc_id = uuid.UUID(r.json()["id"])
    process_document(app_engine, w.tenant_id, doc_id, LocalPdfExtractor())
    while run_once(app_engine):  # process_document jobs were taken directly; this runs match requests
        pass
    with session(w.tenant_id, app_engine) as s:
        inv = s.scalar(select(InvoiceRow).where(InvoiceRow.document_id == doc_id))
        assert inv is not None
        return inv.id


def test_text_pdf_is_read_identified_linked_and_matched(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor I1")
    add_receipt(app_engine, w, "100", date(2026, 10, 8))
    inv = upload_and_process(client, app_engine, w, invoice_pdf("INV-5001"), "k1")
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    review = body["review"]
    assert review["verification_status"] == "passed" and review["document_state"] == "succeeded"
    assert review["fields"]["vendor_id"] == str(w.vendor_id) and review["purchase_order_id"] == str(w.po_id)
    assert review["field_sources"]["doc_number"] == {"source": "read"}
    assert body["lines"][0]["status"] == "matched"  # the match was requested by the extraction itself
    listed = client.get("/api/v1/invoices?verification_status=passed", headers=w.headers).json()
    assert [i["id"] for i in listed["items"]] == [str(inv)]


def test_failed_gates_never_match_then_correction_conflict_and_confirmation(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor I2")
    add_receipt(app_engine, w, "100", date(2026, 10, 8))
    inv = upload_and_process(client, app_engine, w, invoice_pdf("INV-6001", total="999.99"), "k2")
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["review"]["document_state"] == "needs_review"
    assert body["review"]["verification"]["lines_plus_tax_equals_total"] is False
    # False-pass guard: even with a counting receipt, a document that failed the gates is not matched.
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    assert r.status_code == 202
    while run_once(app_engine):
        pass
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] != "matched"
    assert any(e["type"] == "extraction_unverified" for e in body["exceptions"])

    version = body["review"]["version"]
    draft = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"draft": True, "fields": {"total": "420.00"}},
        headers={**w.headers, "If-Match": str(version)},
    )
    assert draft.status_code == 200 and draft.json()["fields"]["total"] == "999.99"
    assert draft.json()["review_draft"]["fields"]["total"] == "420.00"
    version = draft.json()["version"]
    # Two people correct from the same version: one wins, the other gets 409 with the current record.
    first = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"fields": {"total": "420.00"}},
        headers={**w.headers, "If-Match": str(version)},
    )
    second = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"fields": {"total": "1.00"}},
        headers={**w.headers, "If-Match": str(version)},
    )
    assert first.status_code == 200 and second.status_code == 409
    assert second.json()["current"]["fields"]["total"] == "420.00"
    src = first.json()["field_sources"]["total"]
    assert src["source"] == "edited" and src["original"] == "999.99" and src["by"] == str(w.user_id)
    assert (
        client.patch(
            f"/api/v1/invoices/{inv}/extraction", json={"fields": {"total": "1"}}, headers=w.headers
        ).status_code
        == 428
    )
    c = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction",
        headers={**w.headers, "If-Match": str(first.json()["version"])},
    )
    assert c.status_code == 200, c.text
    assert c.json()["verification_status"] == "human_confirmed" and c.json()["match_run_id"]
    while run_once(app_engine):
        pass
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] == "matched" and body["review"]["document_state"] == "succeeded"
    unverified = [e for e in body["exceptions"] if e["type"] == "extraction_unverified"]
    assert unverified and unverified[0]["status"] == "auto_closed"


def test_inconsistent_confirmation_needs_explicit_acceptance(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor I3")
    inv = upload_and_process(client, app_engine, w, invoice_pdf("INV-7001", total="430.00"), "k3")
    v = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]["version"]
    refused = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction", headers={**w.headers, "If-Match": str(v)}
    )
    assert refused.status_code == 422
    # B9: accepting a document that does not add up also needs the clerk's note.
    no_note = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction",
        json={"accept_inconsistent": True},
        headers={**w.headers, "If-Match": str(v)},
    )
    assert no_note.status_code == 422 and "note" in no_note.json()["detail"]
    ok = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction",
        json={"accept_inconsistent": True, "note": "Supplier's total omits the eco fee (synthetic)."},
        headers={**w.headers, "If-Match": str(v)},
    )
    assert ok.status_code == 200 and ok.json()["verification_status"] == "human_confirmed_inconsistent"


def test_batch_status_lists_files_and_unknown_vendor_goes_to_review(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor I4")
    inv = upload_and_process(
        client, app_engine, w, invoice_pdf("INV-8001", vendor="Unknown Vendor Ltd"), "k4"
    )
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["review"]["fields"]["vendor_id"] is None
    assert any(e["type"] == "extraction_unverified" for e in body["exceptions"])
    batches = client.get("/api/v1/intake/batches", headers=w.headers).json()["items"]
    detail = client.get(f"/api/v1/intake/batches/{batches[0]['id']}", headers=w.headers).json()
    assert detail["totals"]["file_count"] == 1 and detail["files"][0]["displayed_state"] == "ready"
