"""Regression tests for review round 1 of B1: B1-001 (A-B-A inputs), B1-006, B1-010, B1-011."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import matchdesk.api.app as api_module
from matchdesk.api.app import create_app
from matchdesk.exceptions import build_match_input, execute_run, request_run
from matchdesk.intake.models import InvoiceRow
from matchdesk.matching import evaluate
from matchdesk.qbo.models import QboBillLineRow, QboBillRow
from matchdesk.tenancy import session
from matchdesk.tenancy.models import IdempotencyKey
from matchdesk.worker.__main__ import run_once

from .seed import NOW, add_invoice, add_receipt, make_tenant

pytestmark = pytest.mark.integration


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def _run(client, engine, w):  # type: ignore[no-untyped-def]
    h = w.headers
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h)
    assert r.status_code in (200, 202), r.text
    drain(engine)
    body = client.get(f"/api/v1/invoices/{w.invoices['oct']}", headers=h).json()
    open_types = sorted(e["type"] for e in body["exceptions"] if e["status"] == "open")
    return r.status_code, r.json()["id"], body["lines"][0]["status"], open_types


def _engine_now(engine, w):  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        res = evaluate(build_match_input(s, [w.invoices["oct"]]))
    return res.lines[0].status.value, sorted(e.type.value for e in res.exceptions if e.status.value == "open")


def test_b1_001_receipts_removed_after_a_match_re_evaluate(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-001 receipts")
    add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "60")
    client = TestClient(create_app())
    a = _run(client, app_engine, w)
    assert a[2] == "exception" and a[3] == ["receipt_absent"]
    add_receipt(app_engine, w, "60", date(2026, 10, 6))
    b = _run(client, app_engine, w)
    assert b[2] == "matched"
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("delete from receipt_lines"))
        s.execute(text("delete from receipts"))
    a2 = _run(client, app_engine, w)
    assert a2[0] == 202 and a2[1] != a[1]  # a new current run, not the old one re-served
    assert (a2[2], a2[3]) == ("exception", ["receipt_absent"]) == _engine_now(app_engine, w)
    # Unchanged inputs while that run is current: reused.
    again = _run(client, app_engine, w)
    assert again[0] == 200 and again[1] == a2[1]


def test_b1_001_voided_vendor_credit_re_evaluates(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-001 credit")
    add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "100")
    add_receipt(app_engine, w, "60", date(2026, 10, 6))
    client = TestClient(create_app())
    assert _run(client, app_engine, w)[3] == ["qty_over_received"]
    with session(w.tenant_id, app_engine) as s:
        vc = QboBillRow(
            tenant_id=w.tenant_id,
            qbo_id="VC1",
            txn_type="vendor_credit",
            vendor_id=w.vendor_id,
            doc_number="VC-1",
            doc_number_norm="VC1",
            txn_date=date(2026, 10, 20),
            total=D("168.00"),
            synced_at=NOW,
        )
        s.add(vc)
        s.flush()
        s.add(
            QboBillLineRow(
                tenant_id=w.tenant_id,
                qbo_bill_id=vc.id,
                qty=D("40"),
                amount=D("168.00"),
                po_line_id=w.po_line_id,
            )
        )
        vc_id = vc.id
    assert _run(client, app_engine, w)[2] == "matched"
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("delete from qbo_bill_lines where qbo_bill_id = :b"), {"b": str(vc_id)})
        s.execute(text("delete from qbo_bills where id = :b"), {"b": str(vc_id)})
    final = _run(client, app_engine, w)
    assert (final[2], final[3]) == ("exception", ["qty_over_received"]) == _engine_now(app_engine, w)


def test_b1_006_vendor_less_test_invoice_is_an_exception(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-006")
    inv = add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "60")
    with session(w.tenant_id, app_engine) as s:
        s.get(InvoiceRow, inv).vendor_id = None  # type: ignore[union-attr]
    client = TestClient(create_app())
    _status, _id, line, open_types = _run(client, app_engine, w)
    assert line == "not_evaluated" and open_types == ["extraction_unverified"]


def test_b1_010_auth_before_validation_and_problem_json(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-010")
    client = TestClient(create_app())
    r = client.post("/api/v1/match-runs", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    r = client.post(
        "/api/v1/match-runs",
        json={"invoice_ids": ["secret-probe"]},
        headers=w.headers,
    )
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    assert "secret-probe" not in r.text


def test_b1_010_expired_key_not_replayed_and_concurrent_key_replays(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-010 keys")
    add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "60")
    client = TestClient(create_app())
    h = {**w.headers, "Idempotency-Key": "k-exp"}
    first = client.post(
        "/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h
    ).json()
    drain(app_engine)
    with session(w.tenant_id, app_engine) as s:
        s.execute(text("update idempotency_keys set expires_at = now() - interval '1 hour'"))
    add_receipt(app_engine, w, "60", date(2026, 10, 6))  # inputs change
    second = client.post("/api/v1/match-runs", json={"invoice_ids": [str(w.invoices["oct"])]}, headers=h)
    assert second.status_code == 202 and second.json()["id"] != first["id"]  # expired key not replayed

    # Concurrent request with one key: the other request stores the key first.
    original = api_module.request_run
    winner: dict[str, str] = {}

    def racing_request_run(s, tenant_id, invoice_ids, *a, **kw):  # type: ignore[no-untyped-def]
        run, created = original(s, tenant_id, invoice_ids, *a, **kw)
        with session(tenant_id, app_engine) as other:
            other.add(
                IdempotencyKey(
                    tenant_id=tenant_id,
                    user_id=w.user_id,
                    key="k-race",
                    request_hash=str(sorted(str(i) for i in invoice_ids)).encode(),
                    response_status=202,
                    result_entity_type="match_run",
                    result_entity_id=winner_run_id,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
        winner["id"] = str(winner_run_id)
        return run, created

    winner_run_id = uuid.UUID(second.json()["id"])
    monkeypatch.setattr(api_module, "request_run", racing_request_run)
    client2 = TestClient(create_app())
    r = client2.post(
        "/api/v1/match-runs",
        json={"invoice_ids": [str(w.invoices["oct"])]},
        headers={**h, "Idempotency-Key": "k-race"},
    )
    assert r.status_code in (200, 202) and r.json()["id"] == winner["id"]


def test_b1_011_out_of_order_runs_leave_current_inputs_result(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "B1-011")
    add_invoice(app_engine, w, "oct", "INV-1000", date(2026, 10, 8), "60")
    with session(w.tenant_id, app_engine) as s:
        old_run, _ = request_run(s, w.tenant_id, [w.invoices["oct"]])  # inputs A: no receipt
    add_receipt(app_engine, w, "60", date(2026, 10, 6))
    with session(w.tenant_id, app_engine) as s:
        new_run, created = request_run(s, w.tenant_id, [w.invoices["oct"]])  # inputs B
    assert created and new_run.id != old_run.id
    # The newer run finishes first, then the older one.
    for run in (new_run, old_run):
        with session(w.tenant_id, app_engine) as s:
            execute_run(s, {"tenant_id": str(w.tenant_id), "match_run_id": str(run.id)})
    with session(w.tenant_id, app_engine) as s:
        current = s.execute(text("select status from line_matches where is_current")).scalars().all()
        open_types = s.execute(text("select type from exceptions where status = 'open'")).scalars().all()
    assert current == ["matched"] and open_types == []
    assert _engine_now(app_engine, w) == ("matched", [])


def test_b1_008_database_refuses_unapproved_unit_changing_alias(app_engine):  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import IntegrityError

    w = make_tenant(app_engine, "B1-008")
    with pytest.raises(IntegrityError), session(w.tenant_id, app_engine) as s:
        s.execute(
            text(
                "insert into item_aliases (tenant_id, vendor_id, supplier_item_code, supplier_item_code_norm, item_id,"
                " supplier_uom, item_uom, conversion_factor, status, created_by) values (:t, :v, 'Z', 'Z', :i, 'CS',"
                " 'EA', 1, 'active', :u)"
            ),
            {"t": str(w.tenant_id), "v": str(w.vendor_id), "i": str(w.item_id), "u": str(w.user_id)},
        )
