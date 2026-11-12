"""Regression tests for the B6 A-to-Z review of 2026-11-13 (back end). IDs are the review's."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from matchdesk.api.app import create_app
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


def test_m1_unmatched_confirmed_invoice_reads_as_pending_until_matched(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B7-M1")
    inv = add_invoice(app_engine, w, "m1", "INV-B7M1", date(2026, 10, 6), "10")
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] is None
    assert body["stale"] is True  # the page keeps polling instead of "Not matched yet"
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    assert r.status_code in (200, 202)
    assert client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["stale"] is True  # queued
    drain(app_engine)
    done = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert done["stale"] is False and done["lines"][0]["status"] is not None


def _approved_report(client, engine):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, "Fictional Distributor B7-M6")
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(engine, w, "oct", "INV-B7M6", date(2026, 10, 6), "100", price="4.35")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(engine)
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    a = client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl)
    assert a.status_code == 200, a.text
    return w, ctrl, d["id"]


def test_m6_no_identical_draft_after_approval(app_engine, client):  # type: ignore[no-untyped-def]
    w, _ctrl, rid = _approved_report(client, app_engine)
    got = client.get(f"/api/v1/reports/backtest/{rid}", headers=w.headers).json()
    assert got["changed_since_cutoff"] is False
    again = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers)
    assert again.status_code == 409 and "nothing changed" in again.json()["title"]
    # The approved version still governs: still approved, no second version.
    items = client.get("/api/v1/reports/backtest", headers=w.headers).json()["items"]
    assert [(r["version_no"], r["status"]) for r in items] == [(1, "approved")]
    # After a real change (a new invoice in the period, matched), a new draft is allowed.
    inv2 = add_invoice(app_engine, w, "oct2", "INV-B7M6b", date(2026, 10, 9), "1", price="4.35")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv2)]}, headers=w.headers)
    drain(app_engine)
    assert client.get(f"/api/v1/reports/backtest/{rid}", headers=w.headers).json()["changed_since_cutoff"]
    assert client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).status_code == 201


def test_m5_csv_labels_match_the_screen(app_engine, client):  # type: ignore[no-untyped-def]
    w, _ctrl, rid = _approved_report(client, app_engine)
    got = client.get(f"/api/v1/reports/backtest/{rid}", headers=w.headers).json()
    out = client.get(f"/api/v1/reports/backtest/{rid}/export?format=csv", headers=w.headers).text
    rows = list(csv.reader(io.StringIO(out)))
    head = dict(zip(rows[0], rows[1], strict=True))
    assert head["flagged_discrepancies"] == got["flagged_amount"]
    assert Decimal(head["flagged_discrepancies"]) == Decimal(head["findings"]) + Decimal(head["not_received"])
    detail = rows[4:]
    assert detail and all(r[9] in ("Yes", "No") for r in detail)
    assert all("_" not in r[0] and "_" not in r[1] for r in detail)  # words, not codes


def test_draft_shows_every_reason_approval_would_give(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B7-DB")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "oct", "INV-B7DB", date(2026, 10, 6), "100", price="4.35")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    drain(app_engine)
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert client.get(f"/api/v1/reports/backtest/{d['id']}", headers=w.headers).json()["blocking"] == []
    add_invoice(app_engine, w, "oct2", "INV-B7DB2", date(2026, 10, 8), "1", price="4.35")  # after the cut-off
    got = client.get(f"/api/v1/reports/backtest/{d['id']}", headers=w.headers).json()["blocking"]
    assert got, "a draft whose inputs changed must say so before the approve dialog"
