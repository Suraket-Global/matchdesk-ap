"""B3 receiving import through the API: IT-07b, UT-30 (class B and C through real imports), the
QuickBooks item-receipt export path (UT-32 rows end to end), XLSX, void and re-match, and a false-pass
guard: a class C or unconfirmed class B import never turns a line into ``matched``."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from matchdesk.api.app import create_app
from matchdesk.exceptions.models import LineMatch
from matchdesk.receiving.models import ReceiptLineRow
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, attest, make_tenant

pytestmark = pytest.mark.integration
MAP = {"po_number": "PO", "line_no": "Line", "qty_received": "Qty", "received_date": "Received", "uom": "UOM"}


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def upload(client, w, data: bytes, evidence_class: str = "A", source_type: str = "spreadsheet", name="r.csv"):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/receiving/imports",
        files={"file": (name, data, "application/octet-stream")},
        data={"evidence_class": evidence_class, "source_type": source_type},
        headers=w.headers,
    )


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def csv_rows(rows: list[str], header: str = "PO,Line,Qty,UOM,Received") -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def test_it07b_preview_commit_twice_and_reupload(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor R1")
    attest(app_engine, w)  # a class A or B import counts only up to the attested class (review m7)
    rows = []
    bad = 0
    for i in range(1221):
        if i % 33 == 0 and bad < 37:
            bad += 1
            kind = bad % 4
            rows.append(
                [
                    "9999,2,1,EA,2026-10-01",
                    "4471,7,1,EA,2026-10-01",
                    "4471,2,0,EA,2026-10-01",
                    "4471,2,1,CS,2026-10-01",
                ][kind]
            )
        else:
            # Any date, including long before the test month: no date-window rejection.
            rows.append(f"4471,2,1,EA,{'2025-01-15' if i % 2 else '2026-10-03'}")
    data = csv_rows(rows)
    r = upload(client, w, data)
    assert r.status_code == 201, r.text
    imp = r.json()
    assert imp["preview"]["rows_total"] == 1221 and imp["state"] == "draft"
    m = client.put(
        f"/api/v1/receiving/imports/{imp['id']}/mapping",
        json={"columns": MAP, "save_as": "warehouse"},
        headers=w.headers,
    )
    assert m.status_code == 200, m.text
    v = m.json()["validation"]
    assert v["rows_valid"] == 1184 and v["rows_rejected"] == 37
    assert {x["reason"] for x in v["rejected_rows"]} == {
        "po_not_found",
        "po_line_not_found",
        "qty_zero",
        "uom_differs_from_po",
    }
    assert all(set(x) == {"row", "reason", "value"} for x in v["rejected_rows"])
    c1 = client.post(f"/api/v1/receiving/imports/{imp['id']}/commit", headers=w.headers)
    assert c1.status_code == 200, c1.text
    c2 = client.post(f"/api/v1/receiving/imports/{imp['id']}/commit", headers=w.headers)
    assert c2.status_code == 200 and c2.json()["state"] == "succeeded"
    with session(w.tenant_id, app_engine) as s:
        n = s.scalar(select(func.count()).select_from(ReceiptLineRow))
    assert n == 1184  # imported once
    again = upload(client, w, data)
    assert again.status_code == 409  # second upload of the same file refused
    detail = client.get(f"/api/v1/receiving/imports/{imp['id']}", headers=w.headers).json()
    assert detail["rows_rejected"] == 37 and len(detail["rejected_rows"]) == 37


def _match(client, app_engine, w, inv) -> dict:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    assert r.status_code in (200, 202), r.text
    drain(app_engine)
    return client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()


def test_ut30_class_c_and_unconfirmed_class_b_never_pass_then_confirmed_class_b_matches(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor R2")
    attest(app_engine, w)  # a class A or B import counts only up to the attested class (review m7)
    inv = add_invoice(app_engine, w, "inv", "INV-2001", date(2026, 10, 10), "100")
    # (a) class C supplier packing slip for 100: stored as context only.
    c = upload(client, w, csv_rows(["4471,2,100,EA,2026-10-05"]), evidence_class="C")
    client.put(
        f"/api/v1/receiving/imports/{c.json()['id']}/mapping", json={"columns": MAP}, headers=w.headers
    )
    assert (
        client.post(f"/api/v1/receiving/imports/{c.json()['id']}/commit", headers=w.headers).status_code
        == 200
    )
    body = _match(client, app_engine, w, inv)
    assert body["lines"][0]["status"] == "exception"
    absent = [e for e in body["exceptions"] if e["type"] == "receipt_absent" and e["status"] == "open"]
    assert absent and absent[0]["sub_reason"] == "supplier_slip_only"
    # (b) class B delivery document for 100 with receiver marks not recorded: still absent.
    b = upload(
        client,
        w,
        csv_rows(["4471,2,100,EA,2026-10-06"], header="PO,Line,Qty,UOM,Received") + b"",
        evidence_class="B",
        source_type="delivery_document",
        name="slip.csv",
    )
    bid = b.json()["id"]
    client.put(f"/api/v1/receiving/imports/{bid}/mapping", json={"columns": MAP}, headers=w.headers)
    client.post(f"/api/v1/receiving/imports/{bid}/commit", headers=w.headers)
    body = _match(client, app_engine, w, inv)
    assert body["lines"][0]["status"] != "matched"
    # (c) the same with marks recorded and the signer named: counts (it arrived after the exception
    # was raised, so it is late evidence and needs the controller first; approve it directly here).
    detail = client.get(f"/api/v1/receiving/imports/{bid}", headers=w.headers).json()
    receipt = detail["receipts"][0]
    stale = client.post(
        f"/api/v1/receiving/receipts/{receipt['id']}/confirm",
        json={"receiver_marks_present": True, "receiver_name": "Synthetic Receiver"},
        headers={**w.headers, "If-Match": "99"},
    )
    assert stale.status_code == 409
    ok = client.post(
        f"/api/v1/receiving/receipts/{receipt['id']}/confirm",
        json={"receiver_marks_present": True, "receiver_name": "Synthetic Receiver"},
        headers={**w.headers, "If-Match": str(receipt["version"])},
    )
    assert ok.status_code == 200, ok.text
    with session(w.tenant_id, app_engine) as s:
        for ln in s.scalars(select(ReceiptLineRow).where(ReceiptLineRow.receiving_import_id == bid)):
            ln.late_approved = True
    body = _match(client, app_engine, w, inv)
    assert body["lines"][0]["status"] == "matched"
    with session(w.tenant_id, app_engine) as s:
        current = s.scalar(select(LineMatch).where(LineMatch.is_current.is_(True)))
        assert current is not None and current.receipt_line_count == 1  # only the class B line counted


def test_void_stops_counting_and_rematches(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor R3")
    attest(app_engine, w)  # a class A or B import counts only up to the attested class (review m7)
    a = upload(client, w, csv_rows(["4471,2,100,EA,2026-10-05"]))
    aid = a.json()["id"]
    client.put(f"/api/v1/receiving/imports/{aid}/mapping", json={"columns": MAP}, headers=w.headers)
    client.post(f"/api/v1/receiving/imports/{aid}/commit", headers=w.headers)
    inv = add_invoice(app_engine, w, "inv", "INV-3001", date(2026, 10, 10), "100")
    assert _match(client, app_engine, w, inv)["lines"][0]["status"] == "matched"
    assert (
        client.post(
            f"/api/v1/receiving/imports/{aid}/void", json={"reason": ""}, headers=w.headers
        ).status_code
        == 422
    )
    v = client.post(f"/api/v1/receiving/imports/{aid}/void", json={"reason": "wrong file"}, headers=w.headers)
    assert v.status_code == 200 and v.json()["state"] == "voided"
    # Stale on read at once, then the triggered re-match stores receipt_absent.
    assert client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["lines"][0]["status"] == "stale"
    drain(app_engine)
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] == "exception"
    assert any(e["type"] == "receipt_absent" and e["status"] == "open" for e in body["exceptions"])


def test_qbo_item_receipt_export_rows_follow_the_independence_rule(app_engine, client):  # type: ignore[no-untyped-def]
    ctrl = make_tenant(app_engine, "Fictional Distributor R4", role="controller")
    att = client.post(
        "/api/v1/receiving/attestation",
        json={
            "evidence_class": "A",
            "source_description": "QuickBooks item receipts entered by the warehouse",
            "ap_staff": ["Pat  Payables"],
        },
        headers=ctrl.headers,
    )
    assert att.status_code == 201, att.text
    header = "PO,Line,Qty,Received,Created by,Created at,Bill created by,Bill created at"
    rows = [
        "4471,2,10,2026-10-02,Wren Warehouse,2026-10-02T09:00:00,Pat Payables,2026-10-05T10:00:00",
        "4471,2,10,2026-10-02,,2026-10-02T09:00:00,,",
        "4471,2,10,2026-10-02,pat payables,2026-10-02T09:00:00,,",
        "4471,2,10,2026-10-02,Wren Warehouse,2026-10-06T09:00:00,Pat Payables,2026-10-05T10:00:00",
    ]
    for bad in (
        upload(
            client, ctrl, csv_rows(rows, header), evidence_class="B", source_type="qbo_item_receipt_export"
        ),
    ):
        assert bad.status_code == 422  # an item-receipt export is always class A
    r = upload(client, ctrl, csv_rows(rows, header), source_type="qbo_item_receipt_export")
    assert r.status_code == 201, r.text
    mapping = {
        "po_number": "PO",
        "line_no": "Line",
        "qty_received": "Qty",
        "received_date": "Received",
        "created_by": "Created by",
        "created_at": "Created at",
        "linked_bill_created_by": "Bill created by",
        "linked_bill_created_at": "Bill created at",
    }
    v = client.put(
        f"/api/v1/receiving/imports/{r.json()['id']}/mapping", json={"columns": mapping}, headers=ctrl.headers
    ).json()["validation"]
    assert v["rows_valid"] == 1
    assert [x["reason"] for x in v["rejected_rows"]] == [
        "creator_unknown",
        "entered_by_ap_staff",
        "entered_after_bill",
    ]


def _xlsx(rows: list[list[str]]) -> bytes:
    def cell(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    body = "".join(
        f'<row r="{i + 1}">' + "".join(cell(f"{chr(65 + j)}{i + 1}", v) for j, v in enumerate(r)) + "</row>"
        for i, r in enumerate(rows)
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
        f'spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def test_xlsx_import_and_hostile_xlsx_refused(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor R5")
    data = _xlsx([["PO", "Line", "Qty", "UOM", "Received"], ["4471", "2", "40", "EA", "46300"]])
    r = upload(client, w, data, name="log.xlsx")
    assert r.status_code == 201, r.text
    v = client.put(
        f"/api/v1/receiving/imports/{r.json()['id']}/mapping", json={"columns": MAP}, headers=w.headers
    ).json()["validation"]
    assert v["rows_valid"] == 1  # Excel serial date read as a date
    hostile = io.BytesIO()
    with zipfile.ZipFile(hostile, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr(
            "xl/worksheets/sheet1.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><worksheet/>'
        )
    assert upload(client, w, hostile.getvalue(), name="x.xlsx").status_code == 422
    assert upload(client, w, b"\x00\x01binary", name="x.bin").status_code == 415
