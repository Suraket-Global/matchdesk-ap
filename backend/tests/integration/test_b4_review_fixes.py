"""Regression tests for the independent B3/B4 review of 2026-11-12 (back end).

One test (or more) per finding; each failed before its fix. IDs are those of the review:
C1, M1 to M7 (critical and major), m1 to m7 (minor).
"""

from __future__ import annotations

import io
import threading
import time
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from matchdesk.api.app import create_app
from matchdesk.exceptions import StaleExceptionVersion, resolve
from matchdesk.exceptions.models import ExceptionRow
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, make_tenant

pytestmark = pytest.mark.integration
OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
QBO_HEADER = "PO,Line,Qty,Received,Created by,Created at,Bill created by,Bill created at"
QBO_MAP = {
    "po_number": "PO",
    "line_no": "Line",
    "qty_received": "Qty",
    "received_date": "Received",
    "created_by": "Created by",
    "created_at": "Created at",
    "linked_bill_created_by": "Bill created by",
    "linked_bill_created_at": "Bill created at",
}


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


def queue(client, headers, **params) -> list[dict]:  # type: ignore[no-untyped-def]
    return client.get("/api/v1/exceptions", params={"limit": 200, **params}, headers=headers).json()["items"]


def post_resolution(client, headers, e, code, note=None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/exceptions/{e['id']}/resolutions",
        json={"code": code, "note": note},
        headers={**headers, "If-Match": str(e["version"])},
    )


def upload(client, w, data: bytes, evidence_class="A", source_type="spreadsheet", name="r.csv"):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/receiving/imports",
        files={"file": (name, data, "application/octet-stream")},
        data={"evidence_class": evidence_class, "source_type": source_type},
        headers=w.headers,
    )


def set_po(engine, w, *, ordered: str | None = None, price: str | None = None) -> None:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        if ordered is not None:
            s.execute(text("update po_lines set qty_ordered = :q"), {"q": ordered})
        if price is not None:
            s.execute(text("update po_lines set unit_price = :p"), {"p": price})


# --- C1 -------------------------------------------------------------------------------------------


def test_c1_item_receipt_export_without_bill_audit_or_attestation_never_counts(app_engine, client):  # type: ignore[no-untyped-def]
    ctrl = make_tenant(app_engine, "Fictional Distributor RV1", role="controller")
    rows = [
        "4471,2,10,2026-10-02,Wren Warehouse,2026-10-02T09:00:00,Pat Payables,2026-10-05T10:00:00",
        "4471,2,10,2026-10-03,Wren Warehouse,2026-10-03T09:00:00,,",
        "4471,2,10,2026-10-04,Wren Warehouse,2026-10-04T09:00:00,Pat Payables,",
    ]
    data = ("\n".join([QBO_HEADER, *rows]) + "\n").encode()
    r = upload(client, ctrl, data, source_type="qbo_item_receipt_export")
    assert r.status_code == 201, r.text
    imp = r.json()["id"]
    v = client.put(
        f"/api/v1/receiving/imports/{imp}/mapping", json={"columns": QBO_MAP}, headers=ctrl.headers
    ).json()["validation"]
    assert v["rows_valid"] == 1
    assert [x["reason"] for x in v["rejected_rows"]] == [
        "linked_bill_creator_unknown",
        "linked_bill_created_at_unknown",
    ]
    # No attestation yet: nobody has named the accounts-payable users, so the commit is refused.
    c = client.post(f"/api/v1/receiving/imports/{imp}/commit", headers=ctrl.headers)
    assert c.status_code == 409, c.text
    att = client.post(
        "/api/v1/receiving/attestation",
        json={
            "evidence_class": "A",
            "source_description": "item receipts by the warehouse",
            "ap_staff": ["Pat Payables"],
        },
        headers=ctrl.headers,
    )
    assert att.status_code == 201, att.text
    c = client.post(f"/api/v1/receiving/imports/{imp}/commit", headers=ctrl.headers)
    assert c.status_code == 200, c.text
    assert c.json()["rows_valid"] == 1


# --- M1 -------------------------------------------------------------------------------------------


def _pending_waiver(client, engine):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, f"Fictional Distributor RV-M1-{uuid.uuid4().hex[:6]}")
    _cid, ctrl = add_user(engine, w, "controller")
    set_po(engine, w, ordered="1000")
    inv = add_invoice(engine, w, "m1", "INV-M1", date(2026, 10, 6), "400", price="4.50")
    match(client, engine, w.headers, [inv])
    pv = queue(client, w.headers, type="price_variance", status="open")[0]
    assert pv["reported_amount"] == "120.00"
    r = post_resolution(client, w.headers, pv, "waived", "supplier agreed price")
    assert r.status_code == 200 and r.json()["result"] == "pending_approval", r.text
    return w, ctrl, inv, pv


def test_m1_rematch_that_closes_the_exception_withdraws_the_pending_waiver(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, inv, pv = _pending_waiver(client, app_engine)
    approval = client.get("/api/v1/approvals", headers=ctrl).json()["items"][0]
    set_po(app_engine, w, price="4.50")  # the PO is corrected: no price variance any more
    match(client, app_engine, w.headers, [inv])
    cur = client.get(f"/api/v1/exceptions/{pv['id']}", headers=w.headers).json()
    assert cur["status"] == "auto_closed"
    assert client.get("/api/v1/approvals", headers=ctrl).json()["items"] == []
    d = client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(approval["version"])},
    )
    assert d.status_code == 409  # never waives an auto-closed exception (false finding)
    cur = client.get(f"/api/v1/exceptions/{pv['id']}", headers=w.headers).json()
    assert cur["status"] == "auto_closed"


def test_m1_rematch_that_changes_the_amount_reopens_and_a_new_request_works(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, inv, pv = _pending_waiver(client, app_engine)
    old = client.get("/api/v1/approvals", headers=ctrl).json()["items"][0]
    set_po(app_engine, w, price="4.10")  # variance now 0.40 x 400 = 160.00
    match(client, app_engine, w.headers, [inv])
    cur = client.get(f"/api/v1/exceptions/{pv['id']}", headers=w.headers).json()
    assert cur["status"] == "open" and cur["reported_amount"] == "160.00"
    stale = client.post(
        f"/api/v1/approvals/{old['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(old["version"])},
    )
    assert stale.status_code == 409  # the old 120.00 request is not applied to a 160.00 exception
    again = post_resolution(client, w.headers, cur, "waived", "new amount, asked again")
    assert again.status_code == 200, again.text  # was a 500 on uq_approvals_pending_exception
    assert again.json()["result"] == "pending_approval"
    pending = client.get("/api/v1/approvals", headers=ctrl).json()["items"]
    assert [a["amount"] for a in pending] == ["160.00"]


# --- M2 and M3: concurrency -------------------------------------------------------------------------


def _hold_then_run(engine, w, first, second):  # type: ignore[no-untyped-def]
    """Run ``first`` in a transaction that stays open, then ``second`` in another; return what
    ``second`` produced and whether it had to wait for ``first`` to commit."""
    started, release = threading.Event(), threading.Event()
    out: dict[str, object] = {}

    def a() -> None:
        with session(w.tenant_id, engine) as s:
            first(s)
            started.set()
            release.wait(10)

    def b() -> None:
        try:
            with session(w.tenant_id, engine) as s:
                out["value"] = second(s)
        except Exception as exc:
            out["value"] = exc
        out["at"] = time.monotonic()

    ta = threading.Thread(target=a)
    ta.start()
    assert started.wait(10)
    tb = threading.Thread(target=b)
    tb.start()
    time.sleep(0.6)
    released = time.monotonic()
    release.set()
    ta.join(10)
    tb.join(10)
    return out["value"], float(out["at"]) >= released  # type: ignore[arg-type]


def test_m2_concurrent_waivers_cannot_pass_the_period_cap_together(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-M2")
    set_po(app_engine, w, ordered="1000")
    ids = [
        add_invoice(app_engine, w, f"m2{i}", f"INV-M2{i}", date(2026, 10, 6 + i), "300", price="4.50")
        for i in range(2)
    ]
    match(client, app_engine, w.headers, ids)
    pv = queue(client, w.headers, type="price_variance", status="open")
    assert [e["reported_amount"] for e in pv] == ["90.00", "90.00"]
    limit, cap = Decimal("100.00"), Decimal("150.00")

    def waive(e):  # type: ignore[no-untyped-def]
        def run(s):  # type: ignore[no-untyped-def]
            row = s.get(ExceptionRow, uuid.UUID(e["id"]))
            return resolve(s, row, w.user_id, "clerk", "waived", "small", e["version"], limit, cap).result

        return run

    second, waited = _hold_then_run(app_engine, w, waive(pv[0]), waive(pv[1]))
    assert waited
    assert second == "pending_approval"  # 90 + 90 above the 150 cap; before the fix both were waived


def test_m3_same_if_match_twice_at_once_gives_one_change_and_one_conflict(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-M3")
    inv = add_invoice(app_engine, w, "m3", "INV-M3", date(2026, 10, 6), "10", price="4.50")
    match(client, app_engine, w.headers, [inv])
    e = queue(client, w.headers, type="price_variance", status="open")[0]

    def go(s):  # type: ignore[no-untyped-def]
        row = s.get(ExceptionRow, uuid.UUID(e["id"]))
        return resolve(
            s, row, w.user_id, "clerk", "source_corrected", None, e["version"], Decimal(100), Decimal(500)
        )

    second, waited = _hold_then_run(app_engine, w, go, go)
    assert waited
    assert isinstance(second, StaleExceptionVersion)  # before the fix both requests succeeded
    events = client.get(f"/api/v1/exceptions/{e['id']}/events", headers=w.headers).json()["items"]
    assert sum(1 for ev in events if ev["event"] == "resolved") == 1


# --- M4, M5, M6 -----------------------------------------------------------------------------------


def _report_world(client, engine):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, f"Fictional Distributor RV-R-{uuid.uuid4().hex[:6]}")
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(engine, w, "r", "INV-R1", date(2026, 10, 6), "100", price="4.35")
    match(client, engine, w.headers, [inv])
    return w, ctrl


def test_m4_approval_refused_when_results_changed_after_the_cut_off(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl = _report_world(client, app_engine)
    draft = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()
    pv = queue(client, w.headers, type="price_variance", status="open")[0]
    assert post_resolution(client, ctrl, pv, "source_corrected").status_code == 200  # after the cut-off
    r = client.post(f"/api/v1/reports/backtest/{draft['id']}/approve", headers=ctrl)
    assert r.status_code == 409 and "cut-off" in r.text
    fresh = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()
    ok = client.post(f"/api/v1/reports/backtest/{fresh['id']}/approve", headers=ctrl)
    assert ok.status_code == 200, ok.text


def test_m5_approved_report_is_immutable_as_a_whole_and_takes_no_new_findings(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl = _report_world(client, app_engine)
    rid = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()["id"]
    assert client.post(f"/api/v1/reports/backtest/{rid}/approve", headers=ctrl).status_code == 200
    for stmt in (
        "update backtest_reports set class_c_only_lines = 99 where id = :r",
        "update backtest_reports set receipt_coverage_pct = 1 where id = :r",
        "update backtest_reports set data_cutoff_at = now() where id = :r",
        "update backtest_reports set status = 'draft' where id = :r",
        "insert into report_findings (tenant_id, report_id, exception_id, section, type, amount, "
        "qualifying, snapshot) select tenant_id, report_id, exception_id, 'finding', type, 999, true, "
        "'{}'::jsonb from report_findings where report_id = :r limit 1",
    ):
        with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
            s.execute(text(stmt), {"r": rid})
    # Superseding is still allowed (a later approval).
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update backtest_reports set status = 'superseded' where id = :r"), {"r": rid})


def test_m6_refund_only_on_the_approved_version_and_threshold_is_not_the_callers(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl = _report_world(client, app_engine)
    r1 = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()["id"]
    assert client.post(f"/api/v1/reports/backtest/{r1}/approve", headers=ctrl).status_code == 200
    ev = client.get(f"/api/v1/reports/backtest/{r1}/refund-evaluation?threshold=1", headers=w.headers)
    assert ev.status_code == 200
    assert ev.json()["threshold"] == "500.00" and ev.json()["refund_due"] is True  # 15.00 < 500.00
    # B6 review M6: a new version after approval needs a real change after the cut-off.
    extra = add_invoice(app_engine, w, "m6b", "INV-M6B", date(2026, 10, 9), "1", price="4.35")
    match(client, app_engine, w.headers, [extra, w.invoices["r"]])
    r2 = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()["id"]
    assert client.post(f"/api/v1/reports/backtest/{r2}/approve", headers=ctrl).status_code == 200
    old = client.get(f"/api/v1/reports/backtest/{r1}/refund-evaluation", headers=w.headers)
    assert old.status_code == 409  # superseded: not the governing version


# --- M7 -------------------------------------------------------------------------------------------


def _xlsx_raw(sheet_rows: str) -> bytes:
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
        f'spreadsheetml/2006/main"><sheetData>{sheet_rows}</sheetData></worksheet>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def test_m7_xlsx_far_column_reference_and_wide_rows_are_refused_quickly(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-M7")
    far = _xlsx_raw('<row r="1"><c r="ZZZZZZZZZZ1" t="inlineStr"><is><t>PO</t></is></c></row>')
    t0 = time.monotonic()
    r = upload(client, w, far, name="far.xlsx")
    assert r.status_code == 422 and time.monotonic() - t0 < 5
    xfe = _xlsx_raw('<row r="1"><c r="XFE1" t="inlineStr"><is><t>PO</t></is></c></row>')
    assert upload(client, w, xfe, name="xfe.xlsx").status_code == 422
    wide = _xlsx_raw('<row r="1"><c r="GT1" t="inlineStr"><is><t>PO</t></is></c></row>')  # column 202
    assert upload(client, w, wide, name="wide.xlsx").status_code == 422


# --- minor findings -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def qbo_endpoint():  # type: ignore[no-untyped-def]
    from matchdesk.qbo import FakeIntuitTokenEndpoint

    return FakeIntuitTokenEndpoint()


@pytest.fixture(scope="module")
def qbo_client(migrated, qbo_endpoint):  # type: ignore[no-untyped-def]
    return TestClient(create_app(qbo_token_endpoint=qbo_endpoint))


def _connect(client, endpoint, w, realm: str) -> str:  # type: ignore[no-untyped-def]
    from urllib.parse import parse_qs, urlparse

    r = client.post("/api/v1/qbo/connection/authorize", headers=w.headers)
    assert r.status_code == 200, r.text
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    cb = client.get(
        "/oauth/intuit/callback",
        params={"state": state, "code": endpoint.issue_code(), "realmId": realm},
        headers={"Cookie": w.headers["Cookie"]},
        follow_redirects=False,
    )
    assert cb.status_code == 303, cb.text  # never a 500
    return str(cb.headers["location"])


def test_m1_minor_reconnecting_another_company_or_a_company_used_elsewhere_is_refused(
    app_engine, qbo_client, qbo_endpoint
):  # type: ignore[no-untyped-def]
    a = make_tenant(app_engine, "Fictional Distributor RV-m1a", role="controller")
    b = make_tenant(app_engine, "Fictional Distributor RV-m1b", role="controller")
    realm = f"realm-{a.tenant_id}"
    assert _connect(qbo_client, qbo_endpoint, a, realm).endswith("result=connected")
    assert qbo_client.delete("/api/v1/qbo/connection", headers=a.headers).status_code == 200
    # The earlier company's data is still held: another company is not mixed into it.
    assert _connect(qbo_client, qbo_endpoint, a, f"realm-other-{a.tenant_id}").endswith("result=refused")
    assert _connect(qbo_client, qbo_endpoint, a, realm).endswith("result=connected")  # same company again
    # A company connected to another account: refused, not a 500.
    assert _connect(qbo_client, qbo_endpoint, b, realm).endswith("result=refused")
    assert qbo_client.get("/api/v1/qbo/connection", headers=b.headers).json()["status"] == "not_connected"


def test_m2_minor_needs_reconnect_survives_the_callers_rollback(app_engine, qbo_client, qbo_endpoint):  # type: ignore[no-untyped-def]
    from matchdesk.core import ConflictError, load_settings
    from matchdesk.qbo import access_token

    w = make_tenant(app_engine, "Fictional Distributor RV-m2", role="controller")
    assert _connect(qbo_client, qbo_endpoint, w, f"realm-{w.tenant_id}").endswith("result=connected")
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update qbo_connections set access_expires_at = now() - interval '1 minute'"))
    qbo_endpoint.expire_refresh = True
    try:
        with pytest.raises(ConflictError), session(w.tenant_id, app_engine) as s:
            access_token(s, load_settings(), qbo_endpoint, w.tenant_id)  # not caught: rolls back
    finally:
        qbo_endpoint.expire_refresh = False
    assert qbo_client.get("/api/v1/qbo/connection", headers=w.headers).json()["status"] == "needs_reconnect"


def test_m3_minor_csv_guard_keeps_negative_amounts_numeric():  # type: ignore[no-untyped-def]
    from matchdesk.reporting.backtest import _cell

    assert _cell(Decimal("-12.50")) == "-12.50" and _cell(3) == "3"
    assert _cell("-cmd") == "'-cmd" and _cell("=1+1") == "'=1+1"


def test_m4_minor_non_utf8_csv_and_bad_shared_string_are_422(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-m4")
    head = b"PO,Line,Qty,UOM,Received\n" + b"4471,2,1,EA,2026-10-01\n" * 4000  # > 64 KB of UTF-8
    assert len(head) > 65536
    r = upload(client, w, head + b"4471,2,1,\xe9A,2026-10-01\n", name="latin1.csv")
    assert r.status_code == 422, r.text
    bad = _xlsx_raw('<row r="1"><c r="A1" t="s"><v>7</v></c></row>')
    assert upload(client, w, bad, name="bad.xlsx").status_code == 422


def test_m5_minor_two_drafts_at_once_get_two_versions(app_engine, client):  # type: ignore[no-untyped-def]
    from matchdesk.reporting import create_draft

    w, _ctrl = _report_world(client, app_engine)
    start, end = date(2026, 10, 1), date(2026, 10, 31)

    def draft(s):  # type: ignore[no-untyped-def]
        return create_draft(s, w.tenant_id, w.user_id, start, end).version_no

    second, waited = _hold_then_run(app_engine, w, draft, draft)
    assert waited and second == 2  # before the fix: a unique violation (500)


def test_m6_minor_po_line_deleted_in_quickbooks_is_no_longer_matchable(app_engine, qbo_client, qbo_endpoint):  # type: ignore[no-untyped-def]
    import copy

    from matchdesk.exceptions import build_match_input
    from matchdesk.qbo import DEFAULT_FIXTURES, RecordedQboReader, execute_sync, request_sync

    w = make_tenant(app_engine, "Fictional Distributor RV-m6", role="controller")
    assert _connect(qbo_client, qbo_endpoint, w, f"realm-{w.tenant_id}").endswith("result=connected")
    reader = RecordedQboReader(DEFAULT_FIXTURES)

    def sync(rdr) -> None:  # type: ignore[no-untyped-def]
        with session(w.tenant_id, app_engine) as s:
            run, _created = request_sync(
                s, w.tenant_id, w.user_id, "date_range", date(2026, 8, 1), date(2026, 10, 31)
            )
            run_id = run.id
        assert execute_sync(app_engine, w.tenant_id, run_id, rdr, page_size=50) == "succeeded"

    sync(reader)
    second = RecordedQboReader(DEFAULT_FIXTURES)
    second.rows = copy.deepcopy(reader.rows)
    po = next(p for p in second.rows["PurchaseOrder"] if p["Id"] == "101")
    po["Line"] = [ln for ln in po["Line"] if str(ln.get("Id")) != "2"]
    sync(second)
    with session(w.tenant_id, app_engine) as s:
        po_row = s.scalar(text("select id from purchase_orders where qbo_id = '101'"))
        removed = s.scalars(
            text("select qbo_line_id from po_lines where purchase_order_id = :p and removed_at is not null"),
            {"p": po_row},
        ).all()
        assert removed == ["2"]
        inv = add_invoice(app_engine, w, "m6", "INV-M6", date(2026, 10, 6), "1")
    with session(w.tenant_id, app_engine) as s:
        s.execute(
            text(
                "update invoices set purchase_order_id = :p, "
                "vendor_id = (select vendor_id from purchase_orders where id = :p) where id = :i"
            ),
            {"p": po_row, "i": inv},
        )
        mi = build_match_input(s, [inv])
        in_scope = [p for p in mi.purchase_orders if p.id == str(po_row)]
        assert len(in_scope) == 1
        line_ids = {ln.id for ln in in_scope[0].lines}
        rows = dict(
            s.execute(
                text("select qbo_line_id, id from po_lines where purchase_order_id = :p"), {"p": po_row}
            ).all()
        )
        assert str(rows["1"]) in line_ids and str(rows["2"]) not in line_ids


def test_m7_minor_import_class_above_the_attested_class_is_not_committed(app_engine, client):  # type: ignore[no-untyped-def]
    from .seed import attest

    w = make_tenant(app_engine, "Fictional Distributor RV-m7")
    mapping = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "uom": "UOM",
    }

    def staged(cls: str, day: int) -> str:
        data = f"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-{day:02d}\n".encode()
        r = upload(client, w, data, evidence_class=cls, name=f"{cls}{day}.csv")
        assert r.status_code == 201, r.text
        client.put(
            f"/api/v1/receiving/imports/{r.json()['id']}/mapping",
            json={"columns": mapping},
            headers=w.headers,
        )
        return str(r.json()["id"])

    def commit(i: str) -> int:
        return int(client.post(f"/api/v1/receiving/imports/{i}/commit", headers=w.headers).status_code)

    a = staged("A", 1)
    assert commit(a) == 409  # no attestation yet
    attest(app_engine, w, "C")
    assert commit(a) == 409  # attested class C only
    assert commit(staged("C", 2)) == 200
    attest(app_engine, w, "A")
    assert commit(a) == 200


# --- web findings that needed the API -------------------------------------------------------------


def test_w3_coverage_is_live_without_a_report_draft(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-W3")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "w3", "INV-W3", date(2026, 10, 6), "100")
    match(client, app_engine, w.headers, [inv])
    r = client.get("/api/v1/coverage", params=OCT, headers=w.headers)
    assert r.status_code == 200, r.text  # was 404: the strip waited for a report
    assert r.json()["item_lines"] == 1 and r.json()["receipt_coverage_pct"] == "100.00"
    assert client.get("/api/v1/reports/backtest", headers=w.headers).json()["items"] == []


def test_w5_mark_reviewed_empties_the_new_alias_list(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-W5", role="controller")
    waiting = [
        a
        for a in client.get("/api/v1/aliases?status=active", headers=w.headers).json()["items"]
        if not a["reviewed_at"]
    ]
    assert len(waiting) == 1
    first = client.post("/api/v1/aliases/review-acknowledgement", headers=w.headers).json()
    assert first["acknowledged"] == 1
    after = client.get("/api/v1/aliases?status=active", headers=w.headers).json()["items"]
    assert all(a["reviewed_at"] for a in after)
    assert (
        client.post("/api/v1/aliases/review-acknowledgement", headers=w.headers).json()["acknowledged"] == 0
    )


def test_w8_background_requests_do_not_reset_the_idle_timer(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-W8")
    from matchdesk.tenancy import global_session

    with global_session(app_engine) as s:
        s.execute(
            text("update sessions set last_seen_at = now() - interval '30 minutes' where user_id = :u"),
            {"u": w.user_id},
        )
    assert (
        client.get("/api/v1/exceptions", headers={**w.headers, "X-Background-Request": "1"}).status_code
        == 200
    )
    with global_session(app_engine) as s:
        idle = s.scalar(
            text("select now() - last_seen_at from sessions where user_id = :u"), {"u": w.user_id}
        )
    assert idle.total_seconds() >= 29 * 60  # polling is not activity
    assert client.get("/api/v1/exceptions", headers=w.headers).status_code == 200
    with global_session(app_engine) as s:
        idle = s.scalar(
            text("select now() - last_seen_at from sessions where user_id = :u"), {"u": w.user_id}
        )
    assert idle.total_seconds() < 60


def test_w8_bulk_retry_with_the_same_key_reports_what_was_applied(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-W8b")
    inv = add_invoice(app_engine, w, "w8", "INV-W8", date(2026, 10, 6), "10", price="4.50")
    match(client, app_engine, w.headers, [inv])
    pv = queue(client, w.headers, type="price_variance", status="open")
    body = {
        "items": [{"id": e["id"], "version": e["version"]} for e in pv],
        "code": "source_corrected",
        "note": None,
    }
    h = {**w.headers, "Idempotency-Key": f"bulk-{uuid.uuid4()}"}
    first = client.post("/api/v1/exceptions/bulk-resolutions", json=body, headers=h)
    again = client.post("/api/v1/exceptions/bulk-resolutions", json=body, headers=h)
    assert first.status_code == 200 and again.status_code == 200, again.text  # was 409, shown as a failure
    assert [r["result"] for r in again.json()["results"]] == ["resolved"]


def test_w7_engine_flags_over_ordered_only_cumulatively(app_engine, client):  # type: ignore[no-untyped-def]
    """Review W7 asked whether the engine raises qty_over_ordered wrongly (FF-1006). It does not: a
    line alone under the ordered quantity is not flagged; the same line after an earlier invoice for
    the full order is, because MatchDesk counts cumulatively (MH-06). The fix is in the words."""
    w = make_tenant(app_engine, "Fictional Distributor RV-W7")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    alone = add_invoice(app_engine, w, "w7a", "INV-W7A", date(2026, 10, 6), "10")
    match(client, app_engine, w.headers, [alone])
    assert not queue(client, w.headers, type="qty_over_ordered")
    w2 = make_tenant(app_engine, "Fictional Distributor RV-W7b")
    add_receipt(app_engine, w2, "100", date(2026, 9, 28))
    full = add_invoice(app_engine, w2, "w7f", "INV-W7F", date(2026, 10, 5), "100")
    more = add_invoice(app_engine, w2, "w7m", "INV-W7M", date(2026, 10, 6), "10")
    match(client, app_engine, w2.headers, [full, more])
    over = queue(client, w2.headers, type="qty_over_ordered")
    assert [e["doc_number"] for e in over] == ["INV-W7M"] and over[0]["variance_qty"].startswith("10")


def test_appflow_s05_s16_columns_and_receipt_lines_name_the_po_line(app_engine, client):  # type: ignore[no-untyped-def]
    from .seed import attest

    w = make_tenant(app_engine, "Fictional Distributor RV-AF", role="controller")
    attest(app_engine, w)
    data = b"PO,Line,Qty,UOM,Received\n4471,2,5,EA,2026-10-01\n"
    imp = upload(client, w, data, name="af.csv").json()["id"]
    client.put(
        f"/api/v1/receiving/imports/{imp}/mapping",
        json={
            "columns": {
                "po_number": "PO",
                "line_no": "Line",
                "qty_received": "Qty",
                "received_date": "Received",
                "uom": "UOM",
            }
        },
        headers=w.headers,
    )
    assert client.post(f"/api/v1/receiving/imports/{imp}/commit", headers=w.headers).status_code == 200
    listed = client.get("/api/v1/receiving/imports", headers=w.headers).json()["items"]
    assert listed[0]["late_lines_waiting"] == 0
    detail = client.get(f"/api/v1/receiving/imports/{imp}", headers=w.headers).json()
    ln = detail["receipts"][0]["lines"][0]
    assert ln["po_line_no"] == 2 and ln["uom"] == "EA"
    users = client.get("/api/v1/users", headers=w.headers).json()["items"]
    assert "last_sign_in_at" in users[0]


def test_appflow_s01_link_carries_the_address_in_the_fragment(app_engine):  # type: ignore[no-untyped-def]
    from . import b2_helpers as b2

    if not b2.mailpit_up():
        pytest.skip("Mailpit is not running on 127.0.0.1:8025")
    w = make_tenant(app_engine, "Fictional Distributor RV-S01")
    with session(w.tenant_id, app_engine) as s:
        address = s.scalar(text("select email from users where id = :u"), {"u": w.user_id})
    c = b2.client()
    assert c.post("/api/v1/auth/login-links", json={"email": address}).status_code in (200, 202)
    found = b2.wait_for_messages(address)
    text_ = b2.message_text(found[0]["ID"])
    assert f"#t={b2.token_from(text_)}&e={address.replace('@', '%40')}" in text_
    b2.delete_messages_to(address)


def test_appflow_s06_s09_duplicate_links_original_and_billed_quantity_is_shown(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor RV-S06")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "s9", "INV-S9", date(2026, 10, 6), "10")
    with session(w.tenant_id, app_engine) as s:
        bill = s.scalar(
            text(
                "insert into qbo_bills (tenant_id, txn_type, qbo_id, vendor_id, doc_number, doc_number_norm, "
                "txn_date, total, balance, paid_status, synced_at) values (:t, 'bill', 'B9', :v, 'B-9', 'b9', "
                "'2026-10-01', 42, 0, 'paid', now()) returning id"
            ),
            {"t": w.tenant_id, "v": w.vendor_id},
        )
        s.execute(
            text(
                "insert into qbo_bill_lines (tenant_id, qbo_bill_id, qty, amount, po_line_id) "
                "values (:t, :b, 10, 42, :pl)"
            ),
            {"t": w.tenant_id, "b": bill, "pl": w.po_line_id},
        )
    match(client, app_engine, w.headers, [inv])
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["purchase_order"]["qbo_billed_qty"] == "10"  # shown greyed, never a receipt
    bid = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    for name in ("a.pdf", "a copy.pdf"):
        r = client.post(
            f"/api/v1/intake/batches/{bid}/files",
            files={"file": (name, b"%PDF-1.4 synthetic s06", "application/pdf")},
            headers={**w.headers, "Idempotency-Key": f"s06-{name}"},
        )
        assert r.status_code in (200, 201), r.text
    drain(app_engine)
    batch = client.get(f"/api/v1/intake/batches/{bid}", headers=w.headers).json()
    dup = [f for f in batch["files"] if f["duplicate_of_document_id"]]
    assert dup and "duplicate_of_invoice_id" in dup[0]
