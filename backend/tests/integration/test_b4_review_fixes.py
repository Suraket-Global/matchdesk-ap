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
