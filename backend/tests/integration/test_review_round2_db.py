"""Regression tests for review round 2 of B1: stale on read (B1-001 open part) and alias changes (MH-10)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from matchdesk.api.app import create_app
from matchdesk.exceptions import rematch_alias
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, make_tenant

pytestmark = pytest.mark.integration


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def _matched_world(app_engine, name):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, name)
    add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "60")
    add_receipt(app_engine, w, "60", date(2026, 10, 6))
    client = TestClient(create_app())
    h = {"Authorization": f"Bearer {w.token}"}
    run_id = client.post(
        "/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h
    ).json()["id"]
    drain(app_engine)
    body = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert body["lines"][0]["status"] == "matched" and body["stale"] is False
    return w, client, h, run_id


def test_b1_001_voided_receipt_import_reads_stale_before_any_new_run(app_engine):  # type: ignore[no-untyped-def]
    w, client, h, run_id = _matched_world(app_engine, "Stale on read")
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update receiving_imports set state = 'voided', voided_at = now()"))
    body = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    line = body["lines"][0]
    assert line["status"] == "stale" and line["stale"] is True and line["result_status"] == "matched"
    assert body["stale"] is True
    assert client.get(f"/api/v1/match-runs/{run_id}", headers=h).json()["stale"] is True
    assert '"status": "matched"' not in str(body).replace("'", '"')
    # Requesting a run re-evaluates; the fresh result is not stale.
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h)
    drain(app_engine)
    after = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert after["lines"][0]["status"] == "exception" and after["stale"] is False
    exc_id = next(e["id"] for e in after["exceptions"] if e["type"] == "receipt_absent")
    assert client.get(f"/api/v1/exceptions/{exc_id}", headers=h).json()["stale"] is False
    # Un-voiding returns to the earlier inputs: stale again until the next run.
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update receiving_imports set state = 'succeeded', voided_at = null"))
    again = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert again["lines"][0]["status"] == "stale"
    assert client.get(f"/api/v1/exceptions/{exc_id}", headers=h).json()["stale"] is True


def test_b1_001_document_added_on_po_in_scope_reads_stale(app_engine):  # type: ignore[no-untyped-def]
    w, client, h, _run = _matched_world(app_engine, "Stale on new document")
    add_invoice(app_engine, w, "nov", "INV-1100", date(2026, 9, 20), "60")  # earlier invoice on the same PO
    body = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert body["lines"][0]["status"] == "stale"


def test_alias_conversion_change_resets_approval_and_rematches(app_engine):  # type: ignore[no-untyped-def]
    w, client, h, _run = _matched_world(app_engine, "Alias change")
    with session(w.tenant_id, app_engine) as s:
        s.execute(
            text(
                "update item_aliases set supplier_uom = 'CS', item_uom = 'EA', conversion_factor = 12, "
                "approved_by = :u, status = 'active'"
            ),
            {"u": str(w.user_id)},
        )
        row = s.execute(text("select status, approved_by from item_aliases")).one()
    # Any change to the conversion clears approval in the database, even when the update sets it.
    assert row[0] == "pending_approval" and row[1] is None
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update item_aliases set approved_by = :u, status = 'active'"), {"u": str(w.user_id)})
        s.execute(text("update item_aliases set conversion_factor = 24"))
        row = s.execute(text("select status, approved_by, version from item_aliases")).one()
    assert row[0] == "pending_approval" and row[1] is None
    assert (
        client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()["lines"][0]["status"] == "stale"
    )
    with session(w.tenant_id, app_engine) as s:
        run = rematch_alias(s, w.tenant_id, w.alias_id)
    assert run is not None and run.trigger == "alias_change"
    drain(app_engine)
    body = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    assert body["lines"][0]["status"] == "exception" and body["stale"] is False
    assert [e["type"] for e in body["exceptions"] if e["status"] == "open"] == ["alias_unconfirmed"]
    assert uuid.UUID(str(run.id))


def _approve_x12(s, w) -> int:  # type: ignore[no-untyped-def]
    s.execute(
        text(
            "update item_aliases set supplier_uom = 'CS', item_uom = 'EA', conversion_factor = 12, "
            "supplier_description = 'Widget, case of 12'"
        )
    )
    s.execute(text("update item_aliases set approved_by = :u, status = 'active'"), {"u": str(w.user_id)})
    row = s.execute(text("select status, approved_by, version from item_aliases")).one()
    assert row[0] == "active" and row[1] is not None
    return int(row[2])


@pytest.mark.parametrize(
    "change",
    [
        "vendor",
        "supplier_item_code",
        "supplier_item_code_norm",
        "supplier_description",
        "description_cleared",
    ],
)
def test_round3_alias_key_change_resets_approval(app_engine, change):  # type: ignore[no-untyped-def]
    """Round-3 observation (MH-10): supplier, supplier item code or description change loses approval."""
    from matchdesk.qbo.models import Vendor

    from .seed import NOW

    w, client, h, _run = _matched_world(app_engine, f"Alias key change {change}")
    with session(w.tenant_id, app_engine) as s:
        version = _approve_x12(s, w)
        params: dict[str, str] = {}
        if change == "vendor":
            v2 = Vendor(tenant_id=w.tenant_id, qbo_id="V2", name="Fictional Supplier U", synced_at=NOW)
            s.add(v2)
            s.flush()
            sql, params = "update item_aliases set vendor_id = :v", {"v": str(v2.id)}
        elif change == "supplier_item_code":
            sql = "update item_aliases set supplier_item_code = 'W-200', supplier_item_code_norm = 'W200'"
        elif change == "supplier_item_code_norm":
            sql = "update item_aliases set supplier_item_code_norm = 'W200'"
        elif change == "supplier_description":
            sql = "update item_aliases set supplier_description = 'Widget, case of 24'"
        else:
            sql = "update item_aliases set supplier_description = null"
        # The same statement also tries to keep the approval: the trigger still clears it.
        s.execute(text(sql + ", approved_by = :u, status = 'active'"), {**params, "u": str(w.user_id)})
        row = s.execute(text("select status, approved_by, version from item_aliases")).one()
    assert row[0] == "pending_approval" and row[1] is None and row[2] == version + 1
    line = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()["lines"][0]
    assert line["status"] != "matched"


def test_round3_alias_unrelated_update_keeps_approval(app_engine):  # type: ignore[no-untyped-def]
    w, _client, _h, _run = _matched_world(app_engine, "Alias unrelated update")
    with session(w.tenant_id, app_engine) as s:
        version = _approve_x12(s, w)
        s.execute(text("update item_aliases set valid_to = now()"))
        row = s.execute(text("select status, approved_by, version from item_aliases")).one()
    assert row[0] == "active" and row[1] is not None and row[2] == version
