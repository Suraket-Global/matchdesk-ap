"""B3 QuickBooks read side without an Intuit account: IT-04, IT-11, UT-14 (recorded responses,
shape unverified until T-1.1.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from matchdesk.api.app import create_app
from matchdesk.core import ConflictError, load_settings
from matchdesk.exceptions import build_match_input
from matchdesk.identity import Membership, Tenant, User, issue_session
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.matching import ExceptionType, evaluate, normalise_number
from matchdesk.qbo import (
    DEFAULT_FIXTURES,
    FakeIntuitTokenEndpoint,
    RecordedQboReader,
    access_token,
    execute_sync,
    request_sync,
)
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow, QboBillLineRow, QboConnection, SyncRun
from matchdesk.tenancy import global_session, session

from .seed import auth_headers

pytestmark = pytest.mark.integration


def bare_tenant(engine, role: str = "controller") -> tuple[uuid.UUID, uuid.UUID, str]:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        t = Tenant(name="Fictional Distributor Q")
        u = User(email=f"{uuid.uuid4().hex[:8]}@example.invalid", display_name="Synthetic controller")
        s.add_all([t, u])
        s.flush()
        tid, uid = t.id, u.id
    with session(tid, engine) as s:
        s.add(Membership(tenant_id=tid, user_id=uid, role=role))
    return tid, uid, issue_session(engine, uid, tid)


def connect(client: TestClient, endpoint: FakeIntuitTokenEndpoint, token: str, realm: str) -> str:
    r = client.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    code = endpoint.issue_code()
    cb = client.get(
        "/oauth/intuit/callback",
        params={"state": state, "code": code, "realmId": realm},
        headers={"Cookie": f"__Host-md_session={token}"},
        follow_redirects=False,
    )
    assert cb.status_code == 303
    return cb.headers["location"]


@pytest.fixture(scope="module")
def endpoint() -> FakeIntuitTokenEndpoint:
    return FakeIntuitTokenEndpoint()


@pytest.fixture(scope="module")
def client(migrated, endpoint):  # type: ignore[no-untyped-def]
    return TestClient(create_app(qbo_token_endpoint=endpoint))


def test_it11_connect_replay_foreign_state_expiry_and_disconnect(app_engine, client, endpoint):  # type: ignore[no-untyped-def]
    tid, _uid, token = bare_tenant(app_engine)
    r = client.post("/api/v1/qbo/connection/authorize", headers=auth_headers(token))
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    code = endpoint.issue_code()
    cookie = {"Cookie": f"__Host-md_session={token}"}
    params = {"state": state, "code": code, "realmId": f"realm-{tid}"}

    # A state presented by another session connects nothing.
    other_tid, _o, other_token = bare_tenant(app_engine)
    foreign = client.get(
        "/oauth/intuit/callback",
        params=params,
        headers={"Cookie": f"__Host-md_session={other_token}"},
        follow_redirects=False,
    )
    assert foreign.headers["location"].endswith("result=refused")
    with session(other_tid, app_engine) as s:
        assert s.scalar(select(func.count()).select_from(QboConnection)) == 0

    first = client.get("/oauth/intuit/callback", params=params, headers=cookie, follow_redirects=False)
    assert first.headers["location"].endswith("result=connected")
    replay = client.get("/oauth/intuit/callback", params=params, headers=cookie, follow_redirects=False)
    assert replay.headers["location"].endswith("result=refused")

    with session(tid, app_engine) as s:
        conns = s.scalars(select(QboConnection)).all()
        assert len(conns) == 1 and conns[0].status == "connected"
        # Stored token is ciphertext, never the plaintext the endpoint issued.
        assert conns[0].refresh_token_enc is not None and b"fake-refresh" not in conns[0].refresh_token_enc
        assert conns[0].refresh_token_enc.startswith(b"v1.")
    status = client.get("/api/v1/qbo/connection", headers=auth_headers(token)).json()
    assert status["status"] == "connected"

    # Refresh refused after expiry: the tenant shows "needs reconnect".
    endpoint.expire_refresh = True
    try:
        with session(tid, app_engine) as s:
            s.execute(text("update qbo_connections set access_expires_at = now() - interval '1 minute'"))
        refused = False
        with session(tid, app_engine) as s:  # the caller catches inside the transaction, so it commits
            try:
                access_token(s, load_settings(), endpoint, tid)
            except ConflictError:
                refused = True
        assert refused
        assert (
            client.get("/api/v1/qbo/connection", headers=auth_headers(token)).json()["status"]
            == "needs_reconnect"
        )
    finally:
        endpoint.expire_refresh = False

    # Disconnect: tokens erased, deletion date set, then sync and match runs are refused.
    gone = client.delete("/api/v1/qbo/connection", headers=auth_headers(token))
    assert gone.status_code == 200 and gone.json()["status"] == "disconnected"
    assert gone.json()["delete_after"] is not None
    with session(tid, app_engine) as s:
        conn = s.scalar(select(QboConnection))
        assert conn is not None and conn.refresh_token_enc is None and conn.access_token_enc is None
        assert conn.delete_after is not None and conn.delete_after > datetime.now(UTC) + timedelta(days=29)
    sync = client.post(
        "/api/v1/qbo/sync-runs",
        json={"mode": "po_references", "po_references": ["4390"]},
        headers=auth_headers(token),
    )
    assert sync.status_code == 409
    with session(tid, app_engine) as s:
        doc_id = _invoice(s, tid, None, "4390", "INV-X1")
    run = client.post("/api/v1/match-runs", json={"invoice_ids": [str(doc_id)]}, headers=auth_headers(token))
    assert run.status_code == 409


def _invoice(s, tid, vendor_id, po_number: str, number: str) -> uuid.UUID:  # type: ignore[no-untyped-def]
    sha = uuid.uuid4().bytes * 2
    doc = DocumentRow(
        tenant_id=tid,
        purpose="invoice",
        source="upload",
        blob_key=f"t/{tid}/invoice/x/{uuid.uuid4()}",
        sha256=sha,
        mime_type="application/pdf",
        byte_size=1,
        state="succeeded",
        correlation_id=uuid.uuid4(),
    )
    s.add(doc)
    s.flush()
    inv = InvoiceRow(
        tenant_id=tid,
        document_id=doc.id,
        file_order_key=sha,
        doc_type="invoice",
        vendor_id=vendor_id,
        doc_number=number,
        doc_number_norm=normalise_number(number),
        doc_date=date(2026, 10, 20),
        po_number_read=po_number,
        total=None,
        currency="CAD",
        verification_status="passed",
    )
    s.add(inv)
    s.flush()
    return inv.id


def _table_counts(engine, tid) -> dict[str, int]:  # type: ignore[no-untyped-def]
    with session(tid, engine) as s:
        return {
            t: int(s.execute(text(f"select count(*) from {t}")).scalar() or 0)  # noqa: S608
            for t in ("vendors", "items", "purchase_orders", "po_lines", "qbo_bills", "qbo_bill_lines")
        }


def test_it04_sync_twice_with_interruption_resumes_and_creates_no_duplicates(app_engine, client, endpoint):  # type: ignore[no-untyped-def]
    tid, uid, token = bare_tenant(app_engine)
    assert connect(client, endpoint, token, f"realm-{tid}").endswith("result=connected")
    reader = RecordedQboReader(DEFAULT_FIXTURES)
    reader.fail_on = {("PurchaseOrder", 3)}  # the worker dies after page 1 of purchase orders
    with session(tid, app_engine) as s:
        run, created = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
        again, created_again = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
        assert created and not created_again and again.id == run.id  # idempotent while pending
        run_id = run.id
    with pytest.raises(Exception, match="simulated interruption"):
        execute_sync(app_engine, tid, run_id, reader, page_size=2)
    with session(tid, app_engine) as s:
        r = s.get(SyncRun, run_id)
        assert r is not None and r.state == "retry_wait" and r.cursor["start"] == 3
    assert execute_sync(app_engine, tid, run_id, reader, page_size=2) == "succeeded"
    po_calls = [c for c in reader.calls if c[0] == "PurchaseOrder"]
    assert po_calls.count(("PurchaseOrder", 1)) == 1  # resume started at page 2, not page 1
    assert po_calls.count(("PurchaseOrder", 3)) == 2
    first = _table_counts(app_engine, tid)
    assert first["purchase_orders"] == 7 and first["qbo_bills"] == 3
    with session(tid, app_engine) as s:
        run2, created2 = request_sync(s, tid, uid, "date_range", date(2026, 8, 1), date(2026, 10, 31))
        assert created2
    assert (
        execute_sync(app_engine, tid, run2.id, RecordedQboReader(DEFAULT_FIXTURES), page_size=2)
        == "succeeded"
    )
    assert _table_counts(app_engine, tid) == first
    body = client.get(f"/api/v1/qbo/sync-runs/{run2.id}", headers=auth_headers(token)).json()
    assert body["state"] == "succeeded" and body["counts"]["PurchaseOrder"] == 7


def test_ut14_po_outside_the_range_is_read_by_reference_with_linked_bills(app_engine, client, endpoint):  # type: ignore[no-untyped-def]
    tid, uid, token = bare_tenant(app_engine)
    connect(client, endpoint, token, f"realm-{tid}")
    with session(tid, app_engine) as s:
        oct_run, _ = request_sync(s, tid, uid, "date_range", date(2026, 10, 1), date(2026, 10, 31))
    execute_sync(app_engine, tid, oct_run.id, RecordedQboReader(DEFAULT_FIXTURES), page_size=100)
    with session(tid, app_engine) as s:
        assert s.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.po_number == "4390")) is None
    r = client.post(
        "/api/v1/qbo/sync-runs",
        json={"mode": "po_references", "po_references": ["4390"]},
        headers={**auth_headers(token), "Idempotency-Key": "sync-4390"},
    )
    assert r.status_code == 202, r.text
    replay = client.post(
        "/api/v1/qbo/sync-runs",
        json={"mode": "po_references", "po_references": ["4390"]},
        headers={**auth_headers(token), "Idempotency-Key": "sync-4390"},
    )
    assert replay.json()["id"] == r.json()["id"]
    execute_sync(
        app_engine, tid, uuid.UUID(r.json()["id"]), RecordedQboReader(DEFAULT_FIXTURES), page_size=100
    )
    with session(tid, app_engine) as s:
        po = s.scalar(select(PurchaseOrderRow).where(PurchaseOrderRow.po_number == "4390"))
        assert po is not None and po.txn_date == date(2026, 8, 14)
        line1 = s.scalar(
            select(PoLineRow).where(PoLineRow.purchase_order_id == po.id, PoLineRow.qbo_line_id == "1")
        )
        assert line1 is not None
        linked = s.scalars(select(QboBillLineRow).where(QboBillLineRow.po_line_id == line1.id)).all()
        assert len(linked) == 1  # the September bill FF-0899, read with no date filter
        inv_id = _invoice(s, tid, po.vendor_id, "4390", "FF-1010")
        s.add(InvoiceLineRow(tenant_id=tid, invoice_id=inv_id, line_no=1, supplier_item_code="HB-M8"))
        s.flush()
        result = evaluate(build_match_input(s, [inv_id]))
    assert not [e for e in result.exceptions if e.type == ExceptionType.NO_PO]
    detail = client.get(f"/api/v1/purchase-orders/{po.id}", headers=auth_headers(token)).json()
    assert detail["po_number"] == "4390" and len(detail["lines"]) == 2
