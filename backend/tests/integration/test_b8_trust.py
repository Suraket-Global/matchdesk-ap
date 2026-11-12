"""B8 (2026-11-13) financial-trust fixes: the queue as one ordered set (full-dataset filters, sort and
keyset cursors), the match view's neighbours, the weekly drill-down scope, and empty versus zero."""

from __future__ import annotations

import os
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from matchdesk.api.app import create_app
from matchdesk.exceptions.models import ExceptionRow
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import World, add_invoice, add_receipt, add_user, attest, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def add_exceptions(engine, w: World, invoice_id: uuid.UUID, values: list[str]) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    """Document-level "no purchase order" exceptions with the given values (synthetic)."""
    ids = []
    with session(w.tenant_id, engine) as s:
        for v in values:
            e = ExceptionRow(
                tenant_id=w.tenant_id,
                fingerprint=os.urandom(16),
                invoice_id=invoice_id,
                type="no_po",
                value_class="open_undecided",
                variance_amount=Decimal(v),
                status="open",
            )
            s.add(e)
            s.flush()
            ids.append(e.id)
    return ids


def all_pages(client, w: World, **params):  # type: ignore[no-untyped-def]
    out, cursor, pages = [], None, 0
    while True:
        q = {"limit": 200, "status": "open", **params}
        if cursor:
            q["cursor"] = cursor
        r = client.get("/api/v1/exceptions", params=q, headers=w.headers)
        assert r.status_code == 200, r.text
        body = r.json()
        out += body["items"]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            return out, body, pages


def test_queue_sorts_and_filters_the_whole_set_before_the_page(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B8-Q1")
    inv = add_invoice(app_engine, w, "q1", "INV-B8Q1", date(2026, 10, 6), "1")
    # 230 rows: 229 small values, then the largest amount inserted last (its id sorts anywhere), and
    # a run of equal values to prove the tie-break is deterministic across pages.
    small = [f"{i}.{i % 100:02d}" for i in range(1, 220)]
    ties = ["50.00"] * 10
    add_exceptions(app_engine, w, inv, small + ties)
    biggest = add_exceptions(app_engine, w, inv, ["999999.99"])[0]
    items, last, pages = all_pages(client, w)
    assert pages == 2 and len(items) == 230 == last["total_count"]
    assert items[0]["id"] == str(biggest)  # the largest amount leads page 1 although it is row 230
    values = [Decimal(e["variance_amount"]) for e in items]
    assert values == sorted(values, reverse=True)
    assert len({e["id"] for e in items}) == 230  # no row twice, none skipped across the cursor
    tied = [e["id"] for e in items if e["variance_amount"] == "50.00"]
    assert tied == sorted(tied)  # equal values: exception id ascending
    # Total value over the full set, exact to the cent (decimal strings, no float).
    assert Decimal(last["total_value"]) == sum(values) and last["total_value"].endswith(str(sum(values))[-3:])
    # A value filter applies before the page: only rows from 100.00 to 150.00, across the set.
    f, body, _ = all_pages(client, w, min_value="100.00", max_value="150.00")
    assert f and all(Decimal("100") <= Decimal(e["variance_amount"]) <= Decimal("150") for e in f)
    assert body["total_count"] == len(f)
    # Oldest first and supplier sorts are total orders too.
    age, _b, _p = all_pages(client, w, sort="age")
    assert len({e["id"] for e in age}) == 230
    assert client.get("/api/v1/exceptions", params={"sort": "price"}, headers=w.headers).status_code == 422
    assert client.get("/api/v1/exceptions", params={"min_value": "abc"}, headers=w.headers).status_code == 422


def test_type_counters_ignore_the_type_filter(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B8-Q2")
    inv = add_invoice(app_engine, w, "q2", "INV-B8Q2", date(2026, 10, 6), "1")
    add_exceptions(app_engine, w, inv, ["1.00", "2.00"])
    body = client.get(
        "/api/v1/exceptions", params={"status": "open", "type": "duplicate"}, headers=w.headers
    ).json()
    assert body["items"] == [] and body["total_count"] == 0 and body["type_counters"] == {"no_po": 2}


def test_neighbours_follow_the_opened_order_beyond_row_200(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B8-Q3")
    inv = add_invoice(app_engine, w, "q3", "INV-B8Q3", date(2026, 10, 6), "1")
    add_exceptions(app_engine, w, inv, [f"{i}.00" for i in range(1, 211)])
    items, _b, _p = all_pages(client, w)
    target = items[204]  # row 205, on the second page
    n = client.get(
        f"/api/v1/exceptions/{target['id']}/neighbours", params={"status": "open"}, headers=w.headers
    ).json()
    assert n["position"] == 205 and n["total"] == 210
    assert n["previous"]["id"] == items[203]["id"] and n["next"]["id"] == items[205]["id"]
    # Returning from the last item: there is no next, and the previous is the row before it.
    last = client.get(
        f"/api/v1/exceptions/{items[-1]['id']}/neighbours", params={"status": "open"}, headers=w.headers
    ).json()
    assert last["next"] is None and last["position"] == 210 and last["previous"]["id"] == items[-2]["id"]
    # After a resolution the exception leaves the set; its neighbours stay the ones around its key.
    with session(w.tenant_id, app_engine) as s:
        row = s.get(ExceptionRow, uuid.UUID(target["id"]))
        assert row is not None
        row.status, row.resolution_code = "resolved", "source_corrected"
    gone = client.get(
        f"/api/v1/exceptions/{target['id']}/neighbours", params={"status": "open"}, headers=w.headers
    ).json()
    assert gone["position"] is None and gone["next"]["id"] == items[205]["id"]


def test_weekly_drilldown_scope_equals_the_report(app_engine, client):  # type: ignore[no-untyped-def]
    """5 to 11 October: one exception for the supplier inside the week; one outside it must not count."""
    w = make_tenant(app_engine, "Fictional Distributor B8-W1")
    add_receipt(app_engine, w, "60", date(2026, 10, 3))
    inside = add_invoice(app_engine, w, "in", "INV-B8W1", date(2026, 10, 7), "100")
    outside = add_invoice(app_engine, w, "out", "INV-B8W2", date(2026, 10, 22), "10", price="0.08")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inside), str(outside)]}, headers=w.headers)
    drain(app_engine)
    week = client.get("/api/v1/weekly-summary?week_start=2026-10-05", headers=w.headers).json()
    row = next(r for r in week["suppliers"] if r["vendor_id"] == str(w.vendor_id))
    scope = {
        "status": "open,pending_approval",
        "vendor_id": str(w.vendor_id),
        "period_start": week["week_start"],
        "period_end": week["week_end"],
        "limit": 200,
    }
    q = client.get("/api/v1/exceptions", params=scope, headers=w.headers).json()
    assert q["total_count"] == row["open_count"] == 1
    assert q["total_value"] == row["open_value"] == "168.00"
    month = client.get(
        "/api/v1/exceptions",
        params={**scope, "period_start": "2026-10-01", "period_end": "2026-10-31"},
        headers=w.headers,
    ).json()
    assert month["total_count"] > q["total_count"]  # the supplier's other exception is outside the week


def test_empty_is_not_zero(app_engine, client):  # type: ignore[no-untyped-def]
    oct_ = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
    w = make_tenant(app_engine, "Fictional Distributor B8-E1")
    fresh = client.get("/api/v1/coverage", params=oct_, headers=w.headers).json()
    assert fresh["state"] == "awaiting_invoices" and fresh["receipt_coverage_pct"] is None
    week = client.get("/api/v1/weekly-summary?week_start=2026-10-05", headers=w.headers).json()
    assert week["state"] == "awaiting_invoices"
    inv = add_invoice(app_engine, w, "e1", "INV-B8E1", date(2026, 10, 6), "10")
    waiting = client.get("/api/v1/coverage", params=oct_, headers=w.headers).json()
    assert waiting["state"] == "processing" and waiting["receipt_coverage_pct"] is None
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    no_log = client.get("/api/v1/coverage", params=oct_, headers=w.headers).json()
    assert no_log["state"] == "awaiting_receiving" and no_log["receipt_coverage_pct"] is None
    # With receiving evidence imported, a measured zero is a real zero, not an empty account.
    w2 = make_tenant(app_engine, "Fictional Distributor B8-E2")
    _c, _h = add_user(app_engine, w2, "controller")
    add_receipt(app_engine, w2, "100", date(2026, 10, 3))
    attest(app_engine, w2)
    inv2 = add_invoice(app_engine, w2, "e2", "INV-B8E2", date(2026, 10, 6), "100")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv2)]}, headers=w2.headers)
    drain(app_engine)
    measured = client.get("/api/v1/coverage", params=oct_, headers=w2.headers).json()
    assert measured["state"] == "measured" and measured["receipt_coverage_pct"] is not None


def test_quickbooks_status_is_the_servers(app_engine, client):  # type: ignore[no-untyped-def]
    """Recorded-response mode is labelled Demo data; the last read comes from the server, not the page."""
    w = make_tenant(app_engine, "Fictional Distributor B8-QB")
    c = client.get("/api/v1/qbo/connection", headers=w.headers).json()
    assert c["source"] == "demo_data" and c["mode"] != "intuit"
    assert c["status"] == "not_connected" and c["last_sync"] is None


def test_conversion_approval_lists_the_lines_it_rematches(app_engine, client):  # type: ignore[no-untyped-def]
    """S-12 (B8): a pending conversion carries the affected lines, before and after conversion."""
    from matchdesk.intake.models import InvoiceLineRow

    w = make_tenant(app_engine, "Fictional Distributor B8-AP")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "ap", "INV-B8AP", date(2026, 10, 14), "4", uom="CS")
    with session(w.tenant_id, app_engine) as s:
        line = s.query(InvoiceLineRow).filter_by(invoice_id=inv).one()
        line.supplier_item_code = "CT-25"
    r = client.post(
        "/api/v1/aliases",
        json={
            "vendor_id": str(w.vendor_id),
            "supplier_item_code": "CT-25",
            "item_id": str(w.item_id),
            "conversion_factor": "25",
            "supplier_uom": "CS",
            "item_uom": "EA",
        },
        headers=w.headers,
    )
    assert r.status_code == 201, r.text
    pending = client.get("/api/v1/approvals?status=pending", headers=ctrl).json()["items"]
    conv = next(a for a in pending if a["subject_type"] == "alias_conversion")
    assert conv["affected"] == [
        {
            "invoice_id": str(inv),
            "invoice_line_id": conv["affected"][0]["invoice_line_id"],
            "doc_number": "INV-B8AP",
            "doc_date": "2026-10-14",
            "line_no": 1,
            "qty": conv["affected"][0]["qty"],
            "uom": "CS",
            "converted_qty": conv["affected"][0]["converted_qty"],
            "open_exceptions": [],
        }
    ]
    assert Decimal(conv["affected"][0]["qty"]) == 4 and Decimal(conv["affected"][0]["converted_qty"]) == 100
