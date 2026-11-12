"""B9 (2026-11-13): the items left that need no outside account. All data synthetic.

1. "No receiving records" declaration (S-03): recorded, audited, lines stay receipt absent.
2. Removing an invoice line in review (S-07): soft, with history, gates re-run, before confirmation.
3. The note on "The document itself does not add up" (S-07): stored, in history and in the report.
4. Saved receiving mappings read and pre-applied; abandoned drafts removed after 7 days (S-05).
5. Assignee filter in the queue scope, cursor and neighbours (S-08).
6. "Changed in QuickBooks" on S-10 from recorded responses.
7. Credit and duplicate decisions (S-09; MH-08, MH-09) with correct netting.
8. Finding outcomes on the governing report (S-13; PRD M-3b, M-3c).
9. Archive export and account deletion through the operator (schema.md 8; S-16, S-18).
"""

from __future__ import annotations

import io
import json
import shutil
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from matchdesk import blobstore
from matchdesk.api.app import create_app
from matchdesk.core import FixedClock
from matchdesk.exceptions.models import ExceptionEvent, ExceptionRow, ItemAlias, LineMatch
from matchdesk.identity import Membership, Tenant, User, enroll_operator, issue_session
from matchdesk.intake.models import InvoiceLineRow, InvoiceRow
from matchdesk.matching import normalise_code
from matchdesk.qbo import (
    DEFAULT_FIXTURES,
    FakeIntuitTokenEndpoint,
    RecordedQboReader,
    execute_sync,
    request_sync,
)
from matchdesk.qbo.models import PoLineChange, PurchaseOrderRow, QboBillRow, Vendor
from matchdesk.receiving import purge_abandoned_drafts
from matchdesk.reporting import execute_due_deletions
from matchdesk.reporting.models import DeletionLedger
from matchdesk.tenancy import global_session, session
from matchdesk.worker.__main__ import run_once

from .seed import NOW, add_invoice, add_receipt, add_user, attest, auth_headers, make_tenant

pytestmark = pytest.mark.integration
OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
ENDPOINT = FakeIntuitTokenEndpoint()


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(qbo_token_endpoint=ENDPOINT))


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def match(client, engine, headers, ids) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(i) for i in ids]}, headers=headers)
    assert r.status_code in (200, 202), r.text  # 200: the current run already covers the inputs
    drain(engine)


def audit_actions(engine, tenant_id) -> list[str]:  # type: ignore[no-untyped-def]
    with session(tenant_id, engine) as s:
        return [r[0] for r in s.execute(text("select action from audit_events order by occurred_at")).all()]


def exceptions_of(engine, w, invoice_id):  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        return list(s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id == invoice_id)).all())


# --- 1. no receiving records ------------------------------------------------------------------


def test_no_receiving_declaration_is_recorded_and_never_a_pass(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-D1")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "d1", "INV-B9D1", date(2026, 10, 6), "10")
    match(client, app_engine, w.headers, [inv])
    before = client.get("/api/v1/coverage", params=OCT, headers=w.headers).json()
    assert before["state"] == "awaiting_receiving" and before["receipt_coverage_pct"] is None
    # Controller only.
    assert client.post("/api/v1/onboarding/no-receiving-declaration", headers=w.headers).status_code == 403
    r = client.post("/api/v1/onboarding/no-receiving-declaration", headers=ctrl)
    assert r.status_code == 201, r.text
    assert r.json()["declaration"]["declared_by_name"] == "Synthetic controller"
    got = client.get("/api/v1/onboarding/no-receiving-declaration", headers=w.headers).json()
    assert got["declaration"]["statement"].startswith("We have no warehouse receiving records")
    # The line is still receipt absent, never matched; coverage is a measured 0 %.
    match(client, app_engine, w.headers, [inv])
    excs = exceptions_of(app_engine, w, inv)
    assert [e.type for e in excs if e.status == "open"] == ["receipt_absent"]
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(select(LineMatch.status).where(LineMatch.is_current.is_(True))) == "exception"
    cov = client.get("/api/v1/coverage", params=OCT, headers=w.headers).json()
    assert cov["state"] == "no_receiving_records" and cov["receipt_coverage_pct"] == "0.00"
    assert cov["no_receiving_declaration"]["declared_by_name"] == "Synthetic controller"
    # The report states it.
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert d["totals"]["no_receiving_declaration"]["declared_by_name"] == "Synthetic controller"
    pdf = client.get(f"/api/v1/reports/backtest/{d['id']}/export?format=pdf", headers=w.headers)
    assert pdf.status_code == 200
    assert "receiving.no_records_declared" in audit_actions(app_engine, w.tenant_id)
    # A committed receiving import withdraws it (audited); declaring is refused while one counts.
    attest(app_engine, w)
    csv_body = b"po_number,line_no,qty,received_date\n4471,2,10,2026-10-03\n"
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("recv.csv", csv_body, "text/csv")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    cols = {
        "po_number": "po_number",
        "line_no": "line_no",
        "qty_received": "qty",
        "received_date": "received_date",
    }
    m = client.put(f"/api/v1/receiving/imports/{up['id']}/mapping", json={"columns": cols}, headers=w.headers)
    assert m.status_code == 200, m.text
    c = client.post(f"/api/v1/receiving/imports/{up['id']}/commit", headers=w.headers)
    assert c.status_code == 200, c.text
    assert (
        client.get("/api/v1/onboarding/no-receiving-declaration", headers=w.headers).json()["declaration"]
        is None
    )
    assert "receiving.no_records_withdrawn" in audit_actions(app_engine, w.tenant_id)
    assert client.post("/api/v1/onboarding/no-receiving-declaration", headers=ctrl).status_code == 409


# --- 2 and 3. removing a line; the note on an inconsistent document -----------------------------


def _second_line(engine, w, inv, qty: str = "5") -> uuid.UUID:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        ln = InvoiceLineRow(
            tenant_id=w.tenant_id,
            invoice_id=inv,
            line_no=2,
            supplier_item_code="W-100",
            qty=D(qty),
            uom="EA",
            unit_price=D("4.20"),
            amount=(D(qty) * D("4.20")).quantize(D("0.01")),
        )
        s.add(ln)
        s.flush()
        return ln.id


def test_remove_line_is_soft_reruns_gates_and_only_before_confirmation(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-L1")
    inv = add_invoice(app_engine, w, "l1", "INV-B9L1", date(2026, 10, 6), "10")  # total 42.00
    extra = _second_line(app_engine, w, inv)  # 21.00 more: the lines no longer add up to 42.00
    add_receipt(app_engine, w, "10", date(2026, 10, 2))
    match(client, app_engine, w.headers, [inv])
    review = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]
    assert len(review["line_fields"]) == 2
    # Version check, then the removal.
    stale = client.post(
        f"/api/v1/invoices/{inv}/lines/{extra}/removal",
        json={"reason": "Printed twice"},
        headers={**w.headers, "If-Match": str(review["version"] + 5)},
    )
    assert stale.status_code == 409
    r = client.post(
        f"/api/v1/invoices/{inv}/lines/{extra}/removal",
        json={"reason": "Line printed twice on the page (synthetic)"},
        headers={**w.headers, "If-Match": str(review["version"])},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [ln["line_no"] for ln in body["line_fields"]] == [1]
    assert body["removed_lines"][0]["line_no"] == 2 and body["removed_lines"][0]["removed_reason"].startswith(
        "Line printed"
    )
    assert body["gates"]["has_lines"] and all(v for v in body["gates"].values())  # 10 x 4.20 = 42.00 again
    assert body["next_line_no"] == 3 and body["document_state"] == "needs_review"
    with session(w.tenant_id, app_engine) as s:
        row = s.get(InvoiceLineRow, extra)
        assert row is not None and row.removed_at is not None  # kept as history
        assert (
            s.scalar(
                select(LineMatch.id).where(LineMatch.invoice_line_id == extra, LineMatch.is_current.is_(True))
            )
            is None
        )
        assert s.scalar(select(LineMatch.id).where(LineMatch.invoice_line_id == extra)) is not None
    assert "invoice.line_removed" in audit_actions(app_engine, w.tenant_id)
    # A removed line number is never reused by an edit.
    reuse = client.patch(
        f"/api/v1/invoices/{inv}/extraction",
        json={"lines": [{"line_no": 2, "qty": "1"}]},
        headers={**w.headers, "If-Match": str(body["version"])},
    )
    assert reuse.status_code == 422
    # Confirm, re-match: the removed line has no result and its exceptions closed.
    ok = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction", headers={**w.headers, "If-Match": str(body["version"])}
    )
    assert ok.status_code == 200, ok.text
    drain(app_engine)
    detail = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert [ln["line_no"] for ln in detail["lines"]] == [1]
    for e in exceptions_of(app_engine, w, inv):
        if e.invoice_line_id == extra:
            assert e.status == "auto_closed"
    # After confirmation a line can no longer be removed.
    keep = detail["lines"][0]["id"]
    late = client.post(
        f"/api/v1/invoices/{inv}/lines/{keep}/removal",
        json={},
        headers={**w.headers, "If-Match": str(detail["review"]["version"])},
    )
    assert late.status_code == 409


def test_inconsistent_note_is_kept_shown_and_reported(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-N1")
    inv = add_invoice(app_engine, w, "n1", "INV-B9N1", date(2026, 10, 6), "10")
    with session(w.tenant_id, app_engine) as s:
        row = s.get(InvoiceRow, inv)
        assert row is not None
        row.total, row.verification_status = D("50.00"), "failed"  # lines 42.00, printed total 50.00
        row.version += 1
    v = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]["version"]
    note = "Supplier added an 8.00 surcharge to the total only (synthetic)."
    r = client.post(
        f"/api/v1/invoices/{inv}/confirm-extraction",
        json={"accept_inconsistent": True, "note": note},
        headers={**w.headers, "If-Match": str(v)},
    )
    assert r.status_code == 200 and r.json()["inconsistent_note"] == note
    review = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["review"]
    assert (
        review["inconsistent_note"] == note
        and review["verification_status"] == "human_confirmed_inconsistent"
    )
    _c, ctrl = add_user(app_engine, w, "controller")
    history = client.get(
        "/api/v1/audit-events", params={"entity_id": str(inv), "limit": 20}, headers=ctrl
    ).json()["items"]
    assert any(h["action"] == "invoice.confirmed" and h["after"].get("note") == note for h in history)
    drain(app_engine)
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert d["totals"]["inconsistent_documents"] == [
        {
            "invoice_id": str(inv),
            "doc_number": "INV-B9N1",
            "vendor_name": "Fictional Supplier T",
            "note": note,
        }
    ]


# --- 4. receiving mappings and abandoned drafts ---------------------------------------------------


def test_saved_mapping_is_read_and_pre_applied(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-M1")
    body = b"PO,Line,Qty,Date\n4471,2,10,2026-10-03\n"
    first = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("a.csv", body, "text/csv")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    assert first["preview"]["applied_mapping"] is None
    cols = {"po_number": "PO", "line_no": "Line", "qty_received": "Qty", "received_date": "Date"}
    put = client.put(
        f"/api/v1/receiving/imports/{first['id']}/mapping",
        json={"columns": cols, "save_as": "Warehouse log"},
        headers=w.headers,
    )
    assert put.status_code == 200, put.text
    listed = client.get("/api/v1/receiving/mappings", headers=w.headers).json()["items"]
    assert [m["name"] for m in listed] == ["Warehouse log"] and listed[0]["columns"] == cols
    second = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("b.csv", b"PO,Line,Qty,Date\n4471,2,5,2026-10-09\n", "text/csv")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    assert second["preview"]["applied_mapping"]["name"] == "Warehouse log"
    assert second["column_map"] == cols and second["mapping_id"] == listed[0]["id"]
    # A file whose headers do not fit is not pre-applied.
    third = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("c.csv", b"Order,Item,Count\n4471,W-100,5\n", "text/csv")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    assert third["preview"]["applied_mapping"] is None and third["column_map"] is None
    _viewer_id, viewer = add_user(app_engine, w, "viewer")
    assert client.get("/api/v1/receiving/mappings", headers=viewer).status_code == 403


def test_abandoned_drafts_are_removed_after_seven_days_with_a_frozen_clock(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-M2")
    old = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("old.csv", b"PO,Line,Qty\n4471,2,1\n", "text/csv")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    with session(w.tenant_id, app_engine) as s:
        key = s.execute(
            text(
                "select d.blob_key from documents d join receiving_imports r on r.document_id = d.id where r.id = :i"
            ),
            {"i": old["id"]},
        ).scalar()
    assert blobstore.get(w.tenant_id, key)
    clock = FixedClock(datetime.now(UTC) + timedelta(days=6, hours=23))
    with session(w.tenant_id, app_engine) as s:
        assert purge_abandoned_drafts(s, clock.now()) == 0  # not yet seven days
    clock = FixedClock(datetime.now(UTC) + timedelta(days=7, minutes=1))
    with session(w.tenant_id, app_engine) as s:
        assert purge_abandoned_drafts(s, clock.now()) == 1
    assert client.get(f"/api/v1/receiving/imports/{old['id']}", headers=w.headers).status_code == 404
    with pytest.raises(Exception):  # noqa: B017 - the stored file is gone
        blobstore.get(w.tenant_id, key)
    assert "receiving.draft_removed" in audit_actions(app_engine, w.tenant_id)
    # A committed import is never removed, however old.
    with session(w.tenant_id, app_engine) as s:
        assert purge_abandoned_drafts(s, datetime.now(UTC) + timedelta(days=400)) == 0


# --- 5. assignee ----------------------------------------------------------------------------------


def test_assignee_filter_is_in_the_scope_cursor_and_neighbours(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-A1")
    ctrl_id, ctrl = add_user(app_engine, w, "controller")
    viewer_id, viewer = add_user(app_engine, w, "viewer")
    inv = add_invoice(app_engine, w, "a1", "INV-B9A1", date(2026, 10, 6), "1")
    ids = []
    with session(w.tenant_id, app_engine) as s:
        for i in range(6):
            e = ExceptionRow(
                tenant_id=w.tenant_id,
                fingerprint=uuid.uuid4().bytes,
                invoice_id=inv,
                type="no_po",
                value_class="open_undecided",
                variance_amount=D(f"{10 + i}.00"),
                status="open",
            )
            s.add(e)
            s.flush()
            ids.append(e.id)
    members = client.get("/api/v1/members", headers=w.headers).json()
    assert {m["role"] for m in members["items"]} == {"clerk", "controller"}  # no viewer
    assert all("email" not in m for m in members["items"])

    def put(eid, uid, headers):  # type: ignore[no-untyped-def]
        v = client.get(f"/api/v1/exceptions/{eid}", headers=headers).json()["version"]
        return client.put(
            f"/api/v1/exceptions/{eid}/assignment",
            json={"user_id": uid},
            headers={**headers, "If-Match": str(v)},
        )

    for eid in ids[:3]:  # 10, 11, 12 to the clerk
        assert put(eid, str(w.user_id), w.headers).status_code == 200
    assert put(ids[3], str(ctrl_id), ctrl).json()["assigned_to_name"] == "Synthetic controller"
    assert put(ids[4], str(viewer_id), ctrl).status_code == 422  # a viewer cannot work it
    assert put(ids[4], str(w.user_id), viewer).status_code == 403
    # Unassign records an event too.
    assert put(ids[3], None, ctrl).json()["assigned_to"] is None
    with session(w.tenant_id, app_engine) as s:
        evs = s.scalars(
            select(ExceptionEvent)
            .where(ExceptionEvent.exception_id == ids[3])
            .order_by(ExceptionEvent.created_at)
        ).all()
        assert [e.event for e in evs] == ["assigned", "assigned"] and evs[1].detail["to"] is None
    assert {"exception.assigned", "exception.unassigned"} <= set(audit_actions(app_engine, w.tenant_id))

    def page(**q):  # type: ignore[no-untyped-def]
        out, cursor = [], None
        while True:
            params = {"status": "open", "limit": 2, **q}
            if cursor:
                params["cursor"] = cursor
            body = client.get("/api/v1/exceptions", params=params, headers=w.headers).json()
            out += body["items"]
            cursor = body["next_cursor"]
            if not cursor:
                return out, body

    mine, body = page(assignee="me")
    assert [i["id"] for i in mine] == [str(x) for x in reversed(ids[:3])] and body["total_count"] == 3
    assert body["total_value"] == "33.00"
    by_id, _ = page(assignee=str(w.user_id))
    assert [i["id"] for i in by_id] == [i["id"] for i in mine]
    none, nb = page(assignee="none")
    assert {i["id"] for i in none} == {str(x) for x in ids[3:]} and nb["total_count"] == 3
    near = client.get(
        f"/api/v1/exceptions/{ids[1]}/neighbours",
        params={"status": "open", "assignee": "me"},
        headers=w.headers,
    ).json()
    assert near["previous"]["id"] == str(ids[2]) and near["next"]["id"] == str(ids[0]) and near["total"] == 3
    assert (
        client.get("/api/v1/exceptions", params={"assignee": "nobody"}, headers=w.headers).status_code == 422
    )


# --- 6. changed in QuickBooks -----------------------------------------------------------------------


def _connected_tenant(engine, client):  # type: ignore[no-untyped-def]
    from urllib.parse import parse_qs, urlparse

    with global_session(engine) as s:
        t = Tenant(name="Fictional Distributor B9-Q1")
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name="Synthetic controller")
        s.add_all([t, u])
        s.flush()
        tid, uid = t.id, u.id
    with session(tid, engine) as s:
        s.add(Membership(tenant_id=tid, user_id=uid, role="controller"))
    token = issue_session(engine, uid, tid)
    r = client.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    cb = client.get(
        "/oauth/intuit/callback",
        params={"state": state, "code": ENDPOINT.issue_code(), "realmId": f"realm-{tid}"},
        headers={"Cookie": f"__Host-md_session={token}"},
        follow_redirects=False,
    )
    assert cb.status_code == 303
    return tid, uid, token


def test_changed_in_quickbooks_banner_from_recorded_responses(app_engine, client, tmp_path):  # type: ignore[no-untyped-def]
    tid, uid, token = _connected_tenant(app_engine, client)
    h = auth_headers(token)
    with session(tid, app_engine) as s:
        run, _ = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
    execute_sync(app_engine, tid, run.id, RecordedQboReader(DEFAULT_FIXTURES), page_size=100)
    drain(app_engine)
    with session(tid, app_engine) as s:
        po = s.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.po_number == "4390"))
        assert po is not None
        po_id, vendor_id = po.id, po.vendor_id
        item_id = s.execute(text("select id from items where qbo_id = '11'")).scalar()
        s.add(
            ItemAlias(
                tenant_id=tid,
                vendor_id=vendor_id,
                supplier_item_code="HB-M8",
                supplier_item_code_norm=normalise_code("HB-M8"),
                item_id=item_id,
                status="active",
                created_by=uid,
            )
        )
        inv = InvoiceRow(
            tenant_id=tid,
            document_id=s.execute(
                text(
                    "insert into documents (tenant_id, purpose, source, blob_key, sha256, mime_type, byte_size,"
                    " state, correlation_id) values (:t, 'invoice', 'upload', :k, :h, 'application/pdf', 1,"
                    " 'succeeded', gen_random_uuid()) returning id"
                ),
                {"t": str(tid), "k": f"t/{tid}/invoice/upload/x/{uuid.uuid4()}", "h": uuid.uuid4().bytes},
            ).scalar(),
            file_order_key=uuid.uuid4().bytes,
            doc_type="invoice",
            vendor_id=vendor_id,
            doc_number="FF-B9Q1",
            doc_number_norm="FFB9Q1",
            doc_date=date(2026, 10, 20),
            po_number_read="4390",
            total=D("21.00"),
            currency="CAD",
            verification_status="passed",
        )
        s.add(inv)
        s.flush()
        s.add(
            InvoiceLineRow(
                tenant_id=tid,
                invoice_id=inv.id,
                line_no=1,
                supplier_item_code="HB-M8",
                qty=D("50"),
                uom="EA",
                unit_price=D("0.42"),
                amount=D("21.00"),
            )
        )
        inv_id = inv.id
    match(client, app_engine, h, [inv_id])
    assert client.get(f"/api/v1/purchase-orders/{po_id}", headers=h).json()["changed_in_quickbooks"] is None
    # Recorded responses after a change in QuickBooks: line 1 ordered 500 -> 450, line 2 deleted.
    changed = tmp_path / "recorded-changed"
    shutil.copytree(DEFAULT_FIXTURES, changed)
    data = json.loads((changed / "PurchaseOrder.json").read_text())
    po101 = next(p for p in data["QueryResponse"]["PurchaseOrder"] if p["Id"] == "101")
    po101["Line"][0]["ItemBasedExpenseLineDetail"]["Qty"] = 450
    po101["Line"] = po101["Line"][:1]
    po101["SyncToken"] = "1"
    (changed / "PurchaseOrder.json").write_text(json.dumps(data))
    with session(tid, app_engine) as s:
        run2, _ = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
    execute_sync(app_engine, tid, run2.id, RecordedQboReader(Path(changed)), page_size=100)
    with session(tid, app_engine) as s:
        rows = s.scalars(select(PoLineChange).where(PoLineChange.purchase_order_id == po_id)).all()
        assert sorted(r.change for r in rows) == ["changed", "removed"]
    banner = client.get(f"/api/v1/purchase-orders/{po_id}", headers=h).json()["changed_in_quickbooks"]
    assert banner is not None and banner["rematched_at"] is None
    by_line = {c["line_no"]: c for c in banner["changes"]}
    assert by_line[1]["before"]["qty_ordered"] == "500" and by_line[1]["after"]["qty_ordered"] == "450"
    assert by_line[2]["change"] == "removed" and by_line[2]["after"] is None
    drain(app_engine)  # the sync's po_change match request
    after = client.get(f"/api/v1/purchase-orders/{po_id}", headers=h).json()["changed_in_quickbooks"]
    assert after["rematched_at"] is not None
    # Reading the same responses again changes nothing more.
    with session(tid, app_engine) as s:
        run3, _ = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
    execute_sync(app_engine, tid, run3.id, RecordedQboReader(Path(changed)), page_size=100)
    with session(tid, app_engine) as s:
        assert s.scalar(text("select count(*) from po_line_changes")) == 2
        with pytest.raises(DBAPIError):
            s.execute(text("update po_line_changes set change = 'removed'"))


# --- 7. credit and duplicate decisions ---------------------------------------------------------------


def _vendor_credit(engine, w, total: str, day: date) -> uuid.UUID:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        vc = QboBillRow(
            tenant_id=w.tenant_id,
            qbo_id=f"VC-{uuid.uuid4().hex[:6]}",
            txn_type="vendor_credit",
            vendor_id=w.vendor_id,
            doc_number="VC-9",
            doc_number_norm="VC9",
            txn_date=day,
            total=D(total),
            synced_at=NOW,
        )
        s.add(vc)
        s.flush()
        return vc.id


def test_credit_decision_nets_once_and_not_credited_is_a_finding(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-C1")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "INV-B9CA", date(2026, 10, 2), "50", price="4.50")  # 15.00 over
    b = add_invoice(app_engine, w, "b", "INV-B9CB", date(2026, 10, 3), "50", price="4.50")  # 15.00 over
    _vendor_credit(app_engine, w, "15.00", date(2026, 10, 20))
    match(client, app_engine, w.headers, [a, b])

    def price(inv):  # type: ignore[no-untyped-def]
        return next(e for e in exceptions_of(app_engine, w, inv) if e.type == "price_variance")

    ea, eb = price(a), price(b)
    # Until decided, both are open and undecided, not findings.
    assert ea.possibly_credited_bill_id and eb.possibly_credited_bill_id
    assert ea.value_class == eb.value_class == "open_undecided" and not ea.qualifying
    body = client.get(f"/api/v1/exceptions/{ea.id}", headers=w.headers).json()
    assert body["possibly_credited"] and body["credit_bill"]["doc_number"] == "VC-9"
    # Clerk cannot decide.
    assert (
        client.post(
            f"/api/v1/exceptions/{ea.id}/credit-decision",
            json={"decision": "credited"},
            headers={**w.headers, "If-Match": str(ea.version)},
        ).status_code
        == 403
    )
    r = client.post(
        f"/api/v1/exceptions/{ea.id}/credit-decision",
        json={"decision": "credited", "note": "VC-9 is the credit for INV-B9CA (synthetic)"},
        headers={**ctrl, "If-Match": str(ea.version)},
    )
    assert r.status_code == 200, r.text and r.json()["match_run_id"]
    drain(app_engine)
    ea, eb = price(a), price(b)
    assert (ea.status, ea.resolution_code, ea.qualifying) == ("resolved", "resolved_by_credit", False)
    assert "decided by the controller" in (ea.label or "")
    # The credit is used once: the other exception is a finding again, not netted a second time.
    assert eb.possibly_credited_bill_id is None and eb.value_class == "finding_candidate" and eb.qualifying
    # Not credited on a fresh pair: a finding, and that credit never flags it again.
    w2 = make_tenant(app_engine, "Fictional Distributor B9-C2")
    _c2, ctrl2 = add_user(app_engine, w2, "controller")
    add_receipt(app_engine, w2, "100", date(2026, 9, 28))
    c = add_invoice(app_engine, w2, "c", "INV-B9CC", date(2026, 10, 2), "100", price="4.35")  # 15.00 over
    _vendor_credit(app_engine, w2, "15.00", date(2026, 10, 25))
    match(client, app_engine, w2.headers, [c])
    ec = next(e for e in exceptions_of(app_engine, w2, c) if e.type == "price_variance")
    assert ec.possibly_credited_bill_id is not None
    r = client.post(
        f"/api/v1/exceptions/{ec.id}/credit-decision",
        json={"decision": "not_credited"},
        headers={**ctrl2, "If-Match": str(ec.version)},
    )
    assert r.status_code == 200, r.text
    drain(app_engine)
    match(client, app_engine, w2.headers, [c])
    ec = next(e for e in exceptions_of(app_engine, w2, c) if e.type == "price_variance")
    assert ec.possibly_credited_bill_id is None and ec.value_class == "finding_candidate" and ec.qualifying
    assert ec.credit_decision == "not_credited"
    with session(w2.tenant_id, app_engine) as s:
        assert s.scalar(
            select(ExceptionEvent.event).where(
                ExceptionEvent.exception_id == ec.id, ExceptionEvent.event == "credit_decided"
            )
        )
    assert "exception.credit_decided" in audit_actions(app_engine, w2.tenant_id)
    # A decided exception is not decided again.
    again = client.post(
        f"/api/v1/exceptions/{ec.id}/credit-decision",
        json={"decision": "credited"},
        headers={**ctrl2, "If-Match": str(ec.version)},
    )
    assert again.status_code == 409


def test_duplicate_decision_endpoint_is_controller_only(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-P1")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "INV-B9PA", date(2026, 10, 2), "10")
    b = add_invoice(app_engine, w, "b", "INV-B9PB", date(2026, 10, 5), "10")  # same total, 3 days later
    match(client, app_engine, w.headers, [a, b])
    pd = next(e for e in exceptions_of(app_engine, w, b) if e.type == "possible_duplicate")
    assert pd.value_class == "open_undecided" and not pd.qualifying
    url = f"/api/v1/exceptions/{pd.id}/duplicate-decision"
    assert (
        client.post(
            url, json={"decision": "is_duplicate"}, headers={**w.headers, "If-Match": str(pd.version)}
        ).status_code
        == 403
    )
    r = client.post(url, json={"decision": "is_duplicate"}, headers={**ctrl, "If-Match": str(pd.version)})
    assert r.status_code == 200, r.text
    assert r.json()["resolution_code"] == "confirmed_duplicate" and r.json()["match_run_id"]
    drain(app_engine)
    after = {e.type: e for e in exceptions_of(app_engine, w, b)}
    # MH-08: once confirmed it is treated as a duplicate (the document total, once) and the
    # possible-duplicate row is closed by the re-match; its decision stays on it.
    assert after["possible_duplicate"].status == "auto_closed"
    assert after["possible_duplicate"].resolution_code == "confirmed_duplicate"
    assert after["duplicate"].status == "open" and after["duplicate"].value_class == "finding_candidate"
    # Only a possible duplicate takes this decision.
    with session(w.tenant_id, app_engine) as s:
        other = ExceptionRow(
            tenant_id=w.tenant_id,
            fingerprint=uuid.uuid4().bytes,
            invoice_id=a,
            type="no_po",
            value_class="unverified",
            status="open",
        )
        s.add(other)
        s.flush()
        other_id = other.id
    refused = client.post(
        f"/api/v1/exceptions/{other_id}/duplicate-decision",
        json={"decision": "not_duplicate"},
        headers={**ctrl, "If-Match": "1"},
    )
    assert refused.status_code == 409


# --- 8. finding outcomes -----------------------------------------------------------------------------


def _governing_report(client, engine, name):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, name)
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(engine, w, "oct", f"INV-{name[-4:]}", date(2026, 10, 6), "100", price="4.35")
    match(client, engine, w.headers, [inv])
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    return w, ctrl, d["id"]


def test_finding_outcomes_follow_the_governing_report_and_stay_separate(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _governing_report(client, app_engine, "Fictional Distributor B9-O1")
    report = client.get(f"/api/v1/reports/backtest/{rid}", headers=ctrl).json()
    finding = next(f for f in report["findings"] if f["section"] == "finding")
    assert finding["amount"] == "15.00"
    url = f"/api/v1/reports/findings/{finding['id']}/outcomes"
    confirm = {"outcome": "controller_confirmed", "amount": "15.00"}
    # Not before the governing version is chosen.
    assert client.post(url, json=confirm, headers=ctrl).status_code == 409
    # The governing version needs a pilot record; the operator creates it.
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(app_engine) as s:
        op = User(email=email, display_name="Synthetic Operator")
        s.add(op)
        s.flush()
        op_id = op.id
    enroll_operator(app_engine, email)
    oh = auth_headers(issue_session(app_engine, op_id, None))
    terms = {"price": "500.00", "period_start": "2026-10-01", "period_end": "2026-10-31"}
    assert (
        client.put(f"/api/v1/operator/tenants/{w.tenant_id}/pilot", json=terms, headers=oh).status_code == 200
    )
    g = client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl)
    assert g.status_code == 200, g.text
    # Clerk cannot record; amounts above the finding are refused; recovery needs a confirmation.
    assert client.post(url, json=confirm, headers=w.headers).status_code == 403
    assert client.post(url, json={**confirm, "amount": "15.01"}, headers=ctrl).status_code == 422
    rec = {"outcome": "credit_recovered", "amount": "10.00", "credit_reference": "QuickBooks credit VC-77"}
    assert client.post(url, json=rec, headers=ctrl).status_code == 409
    ok = client.post(
        url, json={**confirm, "amount": "12.00", "note": "Agreed with the supplier"}, headers=ctrl
    )
    assert ok.status_code == 201, ok.text
    assert client.post(url, json=confirm, headers=ctrl).status_code == 409  # recorded once, never changed
    assert client.post(url, json={**rec, "amount": "12.01"}, headers=ctrl).status_code == 422
    no_ref = client.post(url, json={"outcome": "credit_recovered", "amount": "10.00"}, headers=ctrl)
    assert no_ref.status_code == 422
    done = client.post(url, json=rec, headers=ctrl)
    assert done.status_code == 201, done.text
    totals = client.get(f"/api/v1/reports/backtest/{rid}/outcomes", headers=w.headers).json()
    assert totals["is_governing"] is True
    assert totals["totals"] == {
        "flagged": {"count": 1, "amount": "15.00"},
        "controller_confirmed": {"count": 1, "amount": "12.00"},
        "credit_recovered": {"count": 1, "amount": "10.00"},
    }
    by = totals["by_finding"][finding["id"]]
    assert by["credit_recovered"]["credit_reference"] == "QuickBooks credit VC-77"
    # The report's own figures never change.
    again = client.get(f"/api/v1/reports/backtest/{rid}", headers=ctrl).json()
    assert (
        again["findings_amount"] == report["findings_amount"]
        and again["qualifying_amount"] == report["qualifying_amount"]
    )
    assert {"finding.controller_confirmed", "finding.credit_recovered"} <= set(
        audit_actions(app_engine, w.tenant_id)
    )
    # The database refuses a direct row above the finding and any change.
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
        s.execute(text("update finding_outcomes set amount = 1"))
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
        s.execute(text("delete from finding_outcomes"))


# --- 9. archive export and account deletion ------------------------------------------------------------


def test_archive_export_holds_records_and_originals_and_expires(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B9-X1")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "x1", "INV-B9X1", date(2026, 10, 6), "10")
    assert client.post("/api/v1/exports/archive", headers=w.headers).status_code == 403
    r = client.post("/api/v1/exports/archive", headers=ctrl)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert (
        client.post("/api/v1/exports/archive", headers=ctrl).json()["id"] == r.json()["id"]
    )  # one at a time
    drain(app_engine)
    listed = client.get("/api/v1/exports/archive", headers=ctrl).json()["items"][0]
    assert listed["status"] == "ready" and listed["downloadable"] and listed["file_count"] == 1
    z = client.get(f"/api/v1/exports/archive/{listed['id']}/content", headers=ctrl)
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert {"documents.csv", "invoices.csv", "exceptions.csv", "audit_events.csv", "README.txt"} <= set(names)
    with session(w.tenant_id, app_engine) as s:
        doc_id = s.scalar(select(InvoiceRow.document_id).where(InvoiceRow.id == inv))
    assert f"documents/{doc_id}.pdf" in names
    invoices_csv = zipfile.ZipFile(io.BytesIO(z.content)).read("invoices.csv").decode()
    assert "INV-B9X1" in invoices_csv
    assert {"archive.requested", "archive.ready", "archive.downloaded"} <= set(
        audit_actions(app_engine, w.tenant_id)
    )
    # 24 hours later it is gone (frozen clock).
    from matchdesk.reporting import expire_archives

    assert expire_archives(app_engine, datetime.now(UTC) + timedelta(hours=25)) >= 1
    assert client.get(f"/api/v1/exports/archive/{listed['id']}/content", headers=ctrl).status_code == 404


def test_account_deletion_request_operator_schedule_cancel_and_execute(app_engine, owner_engine, client):  # type: ignore[no-untyped-def]
    keep = make_tenant(app_engine, "Fictional Distributor B9-K1")
    add_invoice(app_engine, keep, "k", "INV-B9K1", date(2026, 10, 6), "10")
    w = make_tenant(app_engine, "Fictional Distributor B9-Z1")
    ctrl_id, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "10", date(2026, 10, 1))
    inv = add_invoice(app_engine, w, "z", "INV-B9Z1", date(2026, 10, 6), "10")
    match(client, app_engine, w.headers, [inv])
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    with session(w.tenant_id, app_engine) as s:
        keys = list(s.scalars(text("select blob_key from documents")).all())
    assert keys
    # Controller only, with the account name typed.
    body = {"reason": "Pilot ended (synthetic)", "confirm_name": "Fictional Distributor B9-Z1"}
    assert client.post("/api/v1/account/deletion-requests", json=body, headers=w.headers).status_code == 403
    wrong = client.post("/api/v1/account/deletion-requests", json={**body, "confirm_name": "x"}, headers=ctrl)
    assert wrong.status_code == 422
    req = client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl)
    assert req.status_code == 201, req.text
    rq = req.json()["request"]
    assert client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl).status_code == 409
    # The controller may cancel; then asks again.
    cancel = client.post(
        f"/api/v1/account/deletion-requests/{rq['id']}/cancel",
        headers={**ctrl, "If-Match": str(rq["version"])},
    )
    assert cancel.status_code == 200 and cancel.json()["request"]["status"] == "cancelled"
    rq = client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl).json()["request"]
    # The operator sees requests (not documents) and schedules it with 30 days' notice.
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(app_engine) as s:
        op = User(email=email, display_name="Synthetic Operator")
        s.add(op)
        s.flush()
        op_id = op.id
    enroll_operator(app_engine, email)
    oh = auth_headers(issue_session(app_engine, op_id, None))
    assert client.get("/api/v1/operator/deletion-requests", headers=ctrl).status_code == 404
    items = client.get("/api/v1/operator/deletion-requests", headers=oh).json()["items"]
    mine = next(i for i in items if i["id"] == rq["id"])
    assert mine["tenant_name"] == "Fictional Distributor B9-Z1" and "INV-B9Z1" not in json.dumps(items)
    s1 = client.post(
        f"/api/v1/operator/deletion-requests/{rq['id']}/decision",
        json={"decision": "schedule", "note": "Pilot ended; archive offered"},
        headers={**oh, "If-Match": str(mine["version"])},
    )
    assert s1.status_code == 200, s1.text
    sched = s1.json()["request"]
    assert sched["status"] == "scheduled"
    after = datetime.fromisoformat(sched["delete_after"])
    assert timedelta(days=29) < after - datetime.now(UTC) <= timedelta(days=30)
    assert {"deletion.requested", "deletion.cancelled", "deletion.scheduled"} <= set(
        audit_actions(app_engine, w.tenant_id)
    )
    # Not yet due: nothing is deleted, and the app role cannot purge early.
    assert w.tenant_id not in execute_due_deletions(app_engine)
    with pytest.raises(DBAPIError), global_session(app_engine) as s:
        s.execute(text("select purge_tenant(:t)"), {"t": str(w.tenant_id)})
    # The app role cannot delete the audit log or approved findings itself, even with app.purge set.
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
        s.execute(text("select set_config('app.purge', 'on', true)"))
        s.execute(text("delete from report_findings"))
    # Due (moved back as the owner, the way 30 days pass): the account goes, the other stays.
    with owner_engine.begin() as c:
        c.execute(
            text("update deletion_requests set delete_after = now() - interval '1 minute' where id = :i"),
            {"i": rq["id"]},
        )
    assert w.tenant_id in execute_due_deletions(app_engine)
    with global_session(app_engine) as s:
        assert s.get(Tenant, w.tenant_id) is None
        ledger = s.scalars(select(DeletionLedger).where(DeletionLedger.tenant_id == w.tenant_id)).all()
        assert len(ledger) == 1 and ledger[0].scope == "tenant" and ledger[0].rows_deleted > 0
        assert ledger[0].requested_by == ctrl_id
    with owner_engine.connect() as c:
        tables = [
            r[0]
            for r in c.execute(
                text(
                    "select table_name from information_schema.columns where column_name = 'tenant_id' "
                    "and table_schema = 'public' and table_name <> 'deletion_ledger'"
                )
            ).all()
        ]
        for t in tables:
            n = c.execute(
                text(f"select count(*) from {t} where tenant_id = :t"),  # noqa: S608
                {"t": str(w.tenant_id)},
            ).scalar()
            assert n == 0, t
    for key in keys:
        with pytest.raises(Exception):  # noqa: B017 - every stored file is gone
            blobstore.get(w.tenant_id, key)
    assert client.get(f"/api/v1/invoices/{inv}", headers=ctrl).status_code in (401, 404)
    with session(keep.tenant_id, app_engine) as s:
        assert s.scalar(text("select count(*) from invoices")) == 1
        assert s.get(Vendor, keep.vendor_id) is not None


# --- section 7 of App-flow.md: S-03 attestation and earlier invoices, S-12 late evidence -------------


def test_onboarding_status_names_the_attestation_and_the_earlier_invoices_needed(app_engine, client):  # type: ignore[no-untyped-def]
    from matchdesk.qbo.models import PoLineRow, QboBillLineRow

    w = make_tenant(app_engine, "Fictional Distributor B9-E1")
    attest(app_engine, w)
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    with session(w.tenant_id, app_engine) as s:
        pl = s.get(PoLineRow, w.po_line_id)
        assert pl is not None
        pl.qbo_billed_qty = D("150")  # QuickBooks shows 150 billed; MatchDesk has a document for 100
        bill = QboBillRow(
            tenant_id=w.tenant_id,
            qbo_id="B-77",
            txn_type="bill",
            vendor_id=w.vendor_id,
            doc_number="FT-0770",
            doc_number_norm="FT0770",
            txn_date=date(2026, 9, 5),
            total=D("210.00"),
            synced_at=NOW,
        )
        s.add(bill)
        s.flush()
        s.add(
            QboBillLineRow(
                tenant_id=w.tenant_id, qbo_bill_id=bill.id, qty=D("50"), amount=D("210.00"), po_line_id=None
            )
        )
    inv = add_invoice(app_engine, w, "e1", "INV-B9E1", date(2026, 10, 6), "100")
    match(client, app_engine, w.headers, [inv])
    assert any(e.type == "history_incomplete" for e in exceptions_of(app_engine, w, inv))
    body = client.get("/api/v1/onboarding/status", headers=w.headers).json()
    assert body["attestation"]["evidence_class"] == "A"
    assert body["attestation"]["attested_by_name"] == "Synthetic user"
    need = body["earlier_invoices_needed"]
    assert need and need[0]["po_number"] == "4471" and need[0]["billed_without_document_qty"] == "50"


def test_late_evidence_approval_lists_the_open_exceptions_it_lets_the_rematch_see(app_engine, client):  # type: ignore[no-untyped-def]
    from matchdesk.exceptions.models import Approval
    from matchdesk.receiving.models import ReceiptLineRow, ReceiptRow, ReceivingImportRow

    w = make_tenant(app_engine, "Fictional Distributor B9-E2")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "60", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "e2", "INV-B9E2", date(2026, 10, 6), "100")
    match(client, app_engine, w.headers, [inv])
    over = next(e for e in exceptions_of(app_engine, w, inv) if e.type == "qty_over_received")
    with session(w.tenant_id, app_engine) as s:
        doc_id = s.execute(text("select document_id from receiving_imports limit 1")).scalar()
        late = ReceivingImportRow(
            tenant_id=w.tenant_id,
            source_type="spreadsheet",
            evidence_class="A",
            document_id=doc_id,
            file_sha256=uuid.uuid4().bytes,
            state="succeeded",
            committed_at=NOW,
        )
        s.add(late)
        s.flush()
        r = ReceiptRow(
            tenant_id=w.tenant_id,
            receiving_import_id=late.id,
            purchase_order_id=w.po_id,
            received_date=date(2026, 10, 1),
        )
        s.add(r)
        s.flush()
        s.add(
            ReceiptLineRow(
                tenant_id=w.tenant_id,
                receipt_id=r.id,
                receiving_import_id=late.id,
                po_line_id=w.po_line_id,
                qty_received=D("40"),
                qty_in_po_uom=D("40"),
                source_row=2,
                added_after_exception=True,
            )
        )
        s.add(
            Approval(
                tenant_id=w.tenant_id,
                subject_type="late_receipt",
                receiving_import_id=late.id,
                requested_by=w.user_id,
                status="pending",
                version=1,
            )
        )
    items = client.get("/api/v1/approvals", headers=ctrl).json()["items"]
    late_item = next(a for a in items if a["subject_type"] == "late_receipt")
    clears = {c["id"]: c for c in late_item["would_clear"]}
    assert str(over.id) in clears and clears[str(over.id)]["value"] == "168.00"
