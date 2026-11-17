"""B16 (2026-11-17): the pilot fee and the refund threshold follow the account's currency.

The owner decided that USD accounts are in scope (Decision.md section 5). The pilot record carries
its fee and currency, always the account's; the refund threshold is the fee (Decision.md 5.1); a
CAD account's fee still defaults to CAD 500 and any other currency has no default, so the operator
enters it on S-18. The refund is evaluated only when the governing report's figures are in the
pilot's currency: never converted, never mixed. All data synthetic.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from matchdesk.api.app import create_app
from matchdesk.audit.models import AuditEvent
from matchdesk.identity import User, enroll_operator, issue_session
from matchdesk.reporting.models import BacktestReport
from matchdesk.tenancy import global_session, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, attest, auth_headers, make_tenant

pytestmark = pytest.mark.integration

OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
TERMS = {"period_start": "2026-10-01", "period_end": "2026-10-31"}


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def _operator(engine):  # type: ignore[no-untyped-def]
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        u = User(email=email, display_name="Synthetic Operator")
        s.add(u)
        s.flush()
        uid = u.id
    enroll_operator(engine, email)
    return auth_headers(issue_session(engine, uid, None))


def _currency(engine, w, code: str) -> None:  # type: ignore[no-untyped-def]
    with global_session(engine) as s:
        s.execute(text("update tenants set currency = :c where id = :t"), {"c": code, "t": w.tenant_id})
    with session(w.tenant_id, engine) as s:
        s.execute(text("update invoices set currency = :c"), {"c": code})


def _approved(client, engine, name: str, code: str):  # type: ignore[no-untyped-def]
    """An approved October version with a qualifying total of 15.00 in ``code``."""
    w = make_tenant(engine, name)
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "100", date(2026, 9, 28))
    attest(engine, w)
    inv = add_invoice(engine, w, "oct", f"INV-{name[-6:]}", date(2026, 10, 6), "100", price="4.35")
    if code != "CAD":
        _currency(engine, w, code)
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    while run_once(engine):
        pass
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers)
    assert d.status_code in (200, 201), d.text
    a = client.post(f"/api/v1/reports/backtest/{d.json()['id']}/approve", headers=ctrl)
    assert a.status_code == 200, a.text
    assert a.json()["qualifying_amount"] == "15.00"
    return w, ctrl, d.json()["id"]


def _pilot(client, w, oh, body, version=None):  # type: ignore[no-untyped-def]
    headers = {**oh, "If-Match": str(version)} if version is not None else oh
    return client.put(f"/api/v1/operator/tenants/{w.tenant_id}/pilot", json=body, headers=headers)


def test_a_usd_account_has_a_usd_pilot_and_its_refund_is_evaluated_in_usd(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _approved(client, app_engine, "Fictional Distributor B16-USD1", "USD")
    oh = _operator(app_engine)
    # No USD price is invented: without an amount the record is refused, naming the currency.
    none = _pilot(client, w, oh, TERMS)
    assert none.status_code == 422 and "USD" in none.text, none.text
    for bad in ("0", "-5", "12.345"):
        assert _pilot(client, w, oh, {**TERMS, "price": bad}).status_code == 422, bad
    made = _pilot(client, w, oh, {**TERMS, "price": "400.00"})
    assert made.status_code == 200, made.text
    p = made.json()
    assert (p["currency"], p["price"], p["refund_threshold"]) == ("USD", "400.00", "400.00")
    # The operator's list says which currency the fee is entered in.
    t = client.get(f"/api/v1/operator/tenants/{w.tenant_id}", headers=oh).json()
    assert t["currency"] == "USD" and t["pilot"]["currency"] == "USD"
    # A threshold apart from the fee is refused (Decision.md 5.1: the threshold is the fee).
    apart = _pilot(client, w, oh, {"refund_threshold": "10.00"}, p["version"])
    assert apart.status_code == 422, apart.text
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers).json()
    assert ev["currency"] == "USD" and ev["threshold_currency"] == "USD"
    assert ev["threshold"] == "400.00" and ev["qualifying_total"] == "15.00" and ev["refund_due"] is True
    g = client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl)
    assert g.status_code == 200, g.text
    assert g.json()["currency"] == "USD" and g.json()["refund_due"] is True
    with session(w.tenant_id, app_engine) as s:
        assert s.get(BacktestReport, uuid.UUID(rid)).currency == "USD"  # frozen with the version
        audit = s.scalar(select(AuditEvent).where(AuditEvent.action == "pilot.governing_set"))
        created = s.scalar(select(AuditEvent).where(AuditEvent.action == "pilot.created"))
    assert audit is not None and audit.after["currency"] == "USD"
    assert created is not None and created.after["currency"] == "USD"
    # Once governing, the fee and its currency are fixed.
    cur = client.get("/api/v1/pilot", headers=w.headers).json()["pilot"]
    assert _pilot(client, w, oh, {"price": "450.00"}, cur["version"]).status_code == 409
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:  # the trigger, too
        s.execute(text("update pilot_engagements set currency = 'CAD'"))


def test_a_cad_account_is_unchanged_at_cad_500(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _approved(client, app_engine, "Fictional Distributor B16-CAD1", "CAD")
    # No pilot record yet: the CAD 500 default threshold, as before.
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers).json()
    assert (ev["threshold"], ev["threshold_currency"], ev["currency"]) == ("500.00", "CAD", "CAD")
    oh = _operator(app_engine)
    made = _pilot(client, w, oh, TERMS)  # no amount: the CAD default
    assert made.status_code == 200, made.text
    p = made.json()
    assert (p["currency"], p["price"], p["refund_threshold"]) == ("CAD", "500.00", "500.00")
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers).json()
    assert ev["threshold"] == "500.00" and ev["threshold_currency"] == "CAD" and ev["refund_due"] is True
    g = client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl)
    assert g.status_code == 200 and g.json()["currency"] == "CAD"


def test_mismatched_currencies_are_refused_never_converted(app_engine, client):  # type: ignore[no-untyped-def]
    # A pilot record from before B16 (CAD 500) on an account whose reports are now in USD.
    w = make_tenant(app_engine, "Fictional Distributor B16-MIX1")
    oh = _operator(app_engine)
    assert _pilot(client, w, oh, TERMS).json()["currency"] == "CAD"
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "100", date(2026, 9, 28))
    attest(app_engine, w)
    inv = add_invoice(app_engine, w, "oct", "INV-B16MIX", date(2026, 10, 6), "100", price="4.35")
    _currency(app_engine, w, "USD")
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=w.headers)
    while run_once(app_engine):
        pass
    rid = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()["id"]
    assert client.post(f"/api/v1/reports/backtest/{rid}/approve", headers=ctrl).status_code == 200
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers)
    assert ev.status_code == 409 and "USD" in ev.text and "CAD" in ev.text and "convert" in ev.text
    g = client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl)
    assert g.status_code == 409 and "convert" in g.text
    assert client.get("/api/v1/pilot", headers=w.headers).json()["pilot"]["governing_report_id"] is None
    # The pure evaluation refuses too.
    from matchdesk.reporting import CurrencyMismatch, refund_evaluation

    with session(w.tenant_id, app_engine) as s:
        r = s.get(BacktestReport, uuid.UUID(rid))
        with pytest.raises(CurrencyMismatch):
            refund_evaluation(r, Decimal("500.00"), threshold_currency="CAD", report_currency="USD")
    # Editing that CAD record on the USD account asks for the USD fee; it is never carried over.
    v = client.get("/api/v1/pilot", headers=w.headers).json()["pilot"]["version"]
    keep = _pilot(client, w, oh, {"payment_status": "paid"}, v)
    assert keep.status_code == 422 and "USD" in keep.text, keep.text
    fixed = _pilot(client, w, oh, {"price": "350.00"}, v)
    assert fixed.status_code == 200 and fixed.json()["currency"] == "USD", fixed.text
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers).json()
    assert ev["threshold"] == "350.00" and ev["threshold_currency"] == "USD" and ev["refund_due"] is True


def test_a_usd_account_without_a_pilot_record_has_no_threshold(app_engine, client):  # type: ignore[no-untyped-def]
    w, _ctrl, rid = _approved(client, app_engine, "Fictional Distributor B16-USD2", "USD")
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation", headers=w.headers)
    assert ev.status_code == 409 and "No pilot fee is recorded for this USD account" in ev.text


def test_pdf_and_csv_state_the_pilot_currency(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _approved(client, app_engine, "Fictional Distributor B16-EXP1", "USD")
    oh = _operator(app_engine)
    assert _pilot(client, w, oh, {**TERMS, "price": "400.00"}).status_code == 200
    assert (
        client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl).status_code == 200
    )
    out = client.get(f"/api/v1/reports/backtest/{rid}/export?format=csv", headers=w.headers).text
    rows = list(csv.reader(io.StringIO(out)))
    head = dict(zip(rows[0], rows[1], strict=True))
    assert head["currency"] == "USD" and head["pilot_currency"] == "USD"
    assert head["pilot_fee"] == "400.00" and head["refund_threshold"] == "400.00"
    assert head["refund_result"] == "Refund applies"
    assert all(r[-1] == "USD" for r in rows[4:])
    pdf = client.get(f"/api/v1/reports/backtest/{rid}/export?format=pdf", headers=w.headers).content
    assert b"Pilot fee USD 400.00" in pdf and b"refund threshold of USD 400.00" in pdf
    assert b"qualifying total USD 15.00 against USD 400.00" in pdf
    assert b"CAD" not in pdf
