"""Free sample check (owner, 2026-11-18): 7 days, up to 100 invoice files, no approved report or
export; the operator starts the pilot, which lifts the limits."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.audit.models import AuditEvent
from matchdesk.core import ConflictError, RecordingMailer
from matchdesk.identity.models import Tenant
from matchdesk.intake.service import add_file, create_batch
from matchdesk.tenancy import global_session, sample, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, make_tenant
from .test_b7_pieces import make_operator

OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(mailer=RecordingMailer()))


def _sample(engine, w, ends: datetime) -> None:  # type: ignore[no-untyped-def]
    with global_session(engine) as g:
        t = g.get(Tenant, w.tenant_id)
        assert t is not None
        t.status, t.sample_ends_at = "sample", ends


def _pdf(n: int) -> bytes:
    return f'%FAKE-PDF\n{{"sample": {n}, "r": "{uuid.uuid4().hex}"}}'.encode()


def test_operator_creates_a_free_sample_by_default_and_starts_the_pilot(app_engine, client):  # type: ignore[no-untyped-def]
    _op, oh = make_operator(app_engine)
    before = datetime.now(UTC)
    r = client.post(
        "/api/v1/operator/tenants", json={"name": f"Fictional Sampleco {uuid.uuid4().hex[:6]}"}, headers=oh
    )
    assert r.status_code == 201, r.text
    row = r.json()
    assert row["status"] == "sample"
    ends = datetime.fromisoformat(row["sample_ends_at"])
    assert before + timedelta(days=7) - timedelta(minutes=1) <= ends <= datetime.now(UTC) + timedelta(days=7)
    paid = client.post(
        "/api/v1/operator/tenants",
        json={"name": f"Fictional Pilotco {uuid.uuid4().hex[:6]}", "offer": "pilot"},
        headers=oh,
    )
    assert paid.json()["status"] == "pilot" and paid.json()["sample_ends_at"] is None
    started = client.post(f"/api/v1/operator/tenants/{row['id']}/start-pilot", headers=oh)
    assert started.status_code == 200 and started.json()["status"] == "pilot"
    assert client.post(f"/api/v1/operator/tenants/{row['id']}/start-pilot", headers=oh).status_code == 409
    with session(uuid.UUID(row["id"]), app_engine) as s:
        assert s.scalar(select(AuditEvent).where(AuditEvent.action == "account.pilot_started")) is not None


def test_sample_refuses_files_beyond_its_limit_and_after_its_end(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Fictional Limitco {uuid.uuid4().hex[:6]}")
    _sample(app_engine, w, datetime.now(UTC) + timedelta(days=7))
    monkeypatch.setattr(sample, "SAMPLE_INVOICE_LIMIT", 2)
    with session(w.tenant_id, app_engine) as s:
        batch = create_batch(s, w.tenant_id)
        bid = batch.id
        add_file(s, w.tenant_id, w.user_id, bid, "k1", _pdf(1))
        add_file(s, w.tenant_id, w.user_id, bid, "k2", _pdf(2))
    with session(w.tenant_id, app_engine) as s:
        again = add_file(s, w.tenant_id, w.user_id, bid, "k2", _pdf(2))  # a retry is answered
        assert again is not None
    with pytest.raises(ConflictError, match="up to 2 invoices"), session(w.tenant_id, app_engine) as s:
        add_file(s, w.tenant_id, w.user_id, bid, "k3", _pdf(3))
    _sample(app_engine, w, datetime.now(UTC) - timedelta(minutes=1))
    monkeypatch.setattr(sample, "SAMPLE_INVOICE_LIMIT", 100)
    with pytest.raises(ConflictError, match="has ended"), session(w.tenant_id, app_engine) as s:
        add_file(s, w.tenant_id, w.user_id, bid, "k4", _pdf(4))
    with session(w.tenant_id, app_engine) as s:
        st = sample.sample_state(s, w.tenant_id)
    assert st is not None and st["ended"] is True and st["invoices_used"] == 2 and st["invoice_limit"] == 100


def test_sample_shows_findings_but_keeps_approval_and_export_for_the_pilot(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, f"Fictional Reportco {uuid.uuid4().hex[:6]}")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(app_engine, w, "oct", "INV-SAMPLE", date(2026, 10, 6), "100", price="4.35")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    while run_once(app_engine):
        pass
    _sample(app_engine, w, datetime.now(UTC) + timedelta(days=7))
    me = client.get("/api/v1/me", headers=ctrl).json()
    assert (
        me["sample"]["invoice_limit"] == 100
        and me["sample"]["invoices_used"] >= 1
        and me["sample"]["ended"] is False
    )
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers)
    assert d.status_code == 201, d.text  # the draft and its findings are shown during the sample
    rid = d.json()["id"]
    assert client.get(f"/api/v1/reports/backtest/{rid}", headers=ctrl).status_code == 200
    refused = client.post(f"/api/v1/reports/backtest/{rid}/approve", headers=ctrl)
    assert refused.status_code == 409 and "paid pilot" in refused.text
    assert client.get(f"/api/v1/reports/backtest/{rid}/export?format=pdf", headers=ctrl).status_code == 409
    with global_session(app_engine) as g:
        g.execute(text("update tenants set status = 'pilot' where id = :t"), {"t": str(w.tenant_id)})
    assert client.post(f"/api/v1/reports/backtest/{rid}/approve", headers=ctrl).status_code == 200
    assert client.get(f"/api/v1/reports/backtest/{rid}/export?format=pdf", headers=ctrl).status_code == 200
    assert client.get("/api/v1/me", headers=ctrl).json()["sample"] is None
