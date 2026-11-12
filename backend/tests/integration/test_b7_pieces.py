"""B7: pilot record (T-5.1.3, IT-26), weekly summary (T-5.1.4, IT-25), operator console and support
grants (T-5.1.5, IT-29), email intake (T-3.3.4, IT-12). All data synthetic."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from matchdesk.api.app import create_app
from matchdesk.core import RecordingMailer, load_settings, text_pdf
from matchdesk.identity import User, enroll_operator, issue_session
from matchdesk.intake import record_usage, sign, signing_key
from matchdesk.intake.models import InvoiceRow, UsageEvent
from matchdesk.reporting import due_weekly
from matchdesk.tenancy import global_session, operator_session, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, auth_headers, make_tenant

pytestmark = pytest.mark.integration
OCT = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
MAILER = RecordingMailer()


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(mailer=MAILER))


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def match(client, engine, headers, ids) -> None:  # type: ignore[no-untyped-def]
    client.post("/api/v1/match-runs", json={"invoice_ids": [str(i) for i in ids]}, headers=headers)
    drain(engine)


def make_operator(engine):  # type: ignore[no-untyped-def]
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        u = User(email=email, display_name="Synthetic Operator")
        s.add(u)
        s.flush()
        uid = u.id
    enroll_operator(engine, email)
    return uid, auth_headers(issue_session(engine, uid, None))


def approved_report(client, engine, name):  # type: ignore[no-untyped-def]
    w = make_tenant(engine, name)
    _c, ctrl = add_user(engine, w, "controller")
    add_receipt(engine, w, "100", date(2026, 9, 28))
    inv = add_invoice(engine, w, "oct", f"INV-{name[-4:]}", date(2026, 10, 6), "100", price="4.35")
    match(client, engine, w.headers, [inv])
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=w.headers).json()
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    return w, ctrl, d["id"]


# --- pilot record, T-5.1.3 ---------------------------------------------------------------------


def test_pilot_record_threshold_and_governing_version(app_engine, client):  # type: ignore[no-untyped-def]
    w, ctrl, rid = approved_report(client, app_engine, "Fictional Distributor PL01")
    _op, oh = make_operator(app_engine)
    terms = {
        "price": "500.00",
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "refund_threshold": "10.00",
        "signed_terms_ref": "Pilot terms v1, signed 2026-10-01 (synthetic)",
    }
    put = client.put(f"/api/v1/operator/tenants/{w.tenant_id}/pilot", json=terms, headers=oh)
    assert put.status_code == 200, put.text
    pilot = put.json()
    assert pilot["refund_threshold"] == "10.00" and pilot["version"] == 1
    # Stale If-Match is refused with the current record.
    stale = client.put(
        f"/api/v1/operator/tenants/{w.tenant_id}/pilot",
        json={"payment_status": "paid"},
        headers={**oh, "If-Match": "7"},
    )
    assert stale.status_code == 409
    # The refund evaluation uses the record's threshold (15.00 qualifying >= 10.00: no refund).
    ev = client.get(f"/api/v1/reports/backtest/{rid}/refund-evaluation?threshold=100000", headers=w.headers)
    assert ev.json()["threshold"] == "10.00" and ev.json()["refund_due"] is False
    # Only a controller sets the governing version, once, from an approved version.
    assert (
        client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=w.headers).status_code
        == 403
    )
    g = client.put("/api/v1/pilot/governing-report", json={"report_id": rid}, headers=ctrl)
    assert g.status_code == 200, g.text
    assert g.json()["refund_qualifying_amount"] == "15.00" and g.json()["refund_due"] is False
    got = client.get("/api/v1/pilot", headers=w.headers).json()
    assert got["governing"]["report_id"] == rid and got["governing"]["version_no"] == 1
    # The threshold can no longer change; the database refuses a changed governing version too.
    t2 = client.put(
        f"/api/v1/operator/tenants/{w.tenant_id}/pilot",
        json={"refund_threshold": "900.00"},
        headers={**oh, "If-Match": str(got["pilot"]["version"])},
    )
    assert t2.status_code == 409
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:
        s.execute(text("update pilot_engagements set governing_report_id = null"))


def test_it26_usage_counted_once_in_the_month_of_first_extraction(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor PL02")
    inv = add_invoice(app_engine, w, "u1", "INV-U1", date(2026, 9, 30), "1")
    with session(w.tenant_id, app_engine) as s:
        row = s.get(InvoiceRow, inv)
        # 23:30 on 31 October in Vancouver is 06:30 UTC on 1 November.
        record_usage(s, w.tenant_id, row.document_id, [row], datetime(2026, 11, 1, 6, 30, tzinfo=UTC))
        record_usage(
            s, w.tenant_id, row.document_id, [row], datetime(2026, 12, 5, tzinfo=UTC)
        )  # re-extraction
    with session(w.tenant_id, app_engine) as s:
        months = s.execute(select(UsageEvent.unit_month)).scalars().all()
    assert months == [date(2026, 10, 1)]  # once, October (Pacific), not the document's September
    with operator_session(app_engine) as s:  # the operator may count units (schema.md 4.3)
        assert (
            s.scalar(text("select count(*) from usage_events where tenant_id = :t"), {"t": str(w.tenant_id)})
            == 1
        )


# --- weekly summary, IT-25 ----------------------------------------------------------------------


def test_it25_weekly_figures_equal_the_queue_and_the_email_has_totals_only(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor WK01")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "60", date(2026, 10, 3))
    a = add_invoice(app_engine, w, "a", "INV-WK1", date(2026, 10, 6), "100", price="4.35")
    b = add_invoice(app_engine, w, "b", "INV-WK2", date(2026, 10, 14), "5")  # another week
    match(client, app_engine, w.headers, [a, b])
    week = client.get("/api/v1/weekly-summary?week_start=2026-10-07", headers=w.headers).json()
    assert week["week_start"] == "2026-10-05" and week["week_end"] == "2026-10-11"
    q = client.get(
        "/api/v1/exceptions",
        params={
            "limit": 200,
            "status": "open,pending_approval",
            "period_start": "2026-10-05",
            "period_end": "2026-10-11",
            "vendor_id": str(w.vendor_id),
        },
        headers=w.headers,
    ).json()["items"]
    value = sum(Decimal(e["reported_amount"] or e["variance_amount"] or "0") for e in q)
    row = week["suppliers"][0]
    assert row["documents"] == 1 and row["open_count"] == len(q) > 0
    assert Decimal(row["open_value"]) == value
    assert week["total"]["open_value"] == row["open_value"]
    MAILER.sent.clear()
    assert (
        client.post(
            "/api/v1/weekly-summary/send", json={"week_start": "2026-10-05"}, headers=w.headers
        ).status_code
        == 403
    )
    sent = client.post("/api/v1/weekly-summary/send", json={"week_start": "2026-10-05"}, headers=ctrl)
    assert sent.status_code == 200 and sent.json()["recipients"] == 1
    assert (
        client.post(
            "/api/v1/weekly-summary/send", json={"week_start": "2026-10-05"}, headers=ctrl
        ).status_code
        == 409
    )
    mail = MAILER.sent[-1]
    assert f"CAD {row['open_value']}" in mail.body and "/reports/weekly?week=2026-10-05" in mail.body
    for secret in ("4.35", "4.20", "INV-WK1", "W-100", "Fictional Supplier T"):
        assert secret not in mail.body and secret not in mail.subject  # no price, document, item or supplier


def test_weekly_job_runs_on_monday_morning_once(app_engine, client):  # type: ignore[no-untyped-def]
    settings = load_settings()
    mailer = RecordingMailer()
    sunday = datetime(2026, 11, 15, 20, 0, tzinfo=UTC)
    assert due_weekly(app_engine, sunday, mailer, settings) == 0
    monday = datetime(2026, 11, 16, 17, 0, tzinfo=UTC)  # 09:00 Pacific
    first = due_weekly(app_engine, monday, mailer, settings)
    assert first >= 1
    assert due_weekly(app_engine, monday + timedelta(minutes=1), mailer, settings) == 0


# --- operator console and support grants, IT-29 ---------------------------------------------------


def test_it29_operator_needs_an_active_grant_and_reads_only(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor OP01")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "o", "INV-OP1", date(2026, 10, 6), "10")
    _op_id, oh = make_operator(app_engine)
    # The console lists the account without any of its documents.
    listing = client.get("/api/v1/operator/tenants", headers=oh)
    assert listing.status_code == 200
    assert "INV-OP1" not in listing.text and any(t["id"] == str(w.tenant_id) for t in listing.json()["items"])
    # Tenant data: nothing without a grant.
    assert client.get(f"/api/v1/invoices/{inv}", headers=oh).status_code == 404
    assert client.get("/api/v1/operator/tenants", headers=w.headers).status_code == 404  # not for tenants
    req = client.post(
        f"/api/v1/operator/tenants/{w.tenant_id}/support-grants",
        json={"hours": 24, "reason": "Help with the October back-test (synthetic)"},
        headers=oh,
    )
    assert req.status_code == 201, req.text
    gid = req.json()["id"]
    # A request is not a grant.
    assert (
        client.post("/api/v1/operator/support-session", json={"grant_id": gid}, headers=oh).status_code == 404
    )
    assert (
        client.post(
            f"/api/v1/support-grants/{gid}/decision", json={"decision": "grant"}, headers=w.headers
        ).status_code
        == 403
    )
    ok = client.post(f"/api/v1/support-grants/{gid}/decision", json={"decision": "grant"}, headers=ctrl)
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    assert (
        client.post("/api/v1/operator/support-session", json={"grant_id": gid}, headers=oh).status_code == 200
    )
    me = client.get("/api/v1/me", headers=oh).json()
    assert me["role"] == "support_reader" and me["support"]["grant_id"] == gid
    assert client.get(f"/api/v1/invoices/{inv}", headers=oh).status_code == 200  # reads
    write = client.post("/api/v1/match-runs", json={"invoice_ids": [str(inv)]}, headers=oh)
    assert write.status_code == 403  # never writes
    # The controller ends it early: the operator sees nothing again at once.
    end = client.post(f"/api/v1/support-grants/{gid}/decision", json={"decision": "end"}, headers=ctrl)
    assert end.status_code == 200 and end.json()["status"] == "ended"
    assert client.get(f"/api/v1/invoices/{inv}", headers=oh).status_code == 404
    assert (
        client.post("/api/v1/operator/support-session", json={"grant_id": gid}, headers=oh).status_code == 404
    )
    actions = client.get("/api/v1/audit-events?limit=50&action=support_grant", headers=ctrl).json()["items"]
    assert {a["action"] for a in actions} >= {
        "support_grant.requested",
        "support_grant.granted",
        "support_grant.entered",
        "support_grant.ended",
    }


def test_it29_expired_grant_reads_nothing(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor OP02")
    _c, ctrl = add_user(app_engine, w, "controller")
    inv = add_invoice(app_engine, w, "o", "INV-OP2", date(2026, 10, 6), "10")
    _op, oh = make_operator(app_engine)
    gid = client.post(
        f"/api/v1/operator/tenants/{w.tenant_id}/support-grants",
        json={"hours": 1, "reason": "check"},
        headers=oh,
    ).json()["id"]
    client.post(f"/api/v1/support-grants/{gid}/decision", json={"decision": "grant"}, headers=ctrl)
    client.post("/api/v1/operator/support-session", json={"grant_id": gid}, headers=oh)
    with session(w.tenant_id, app_engine) as s:  # an hour later
        s.execute(
            text(
                "update support_grants set starts_at = now() - interval '2 hours', "
                "ends_at = now() - interval '1 hour' where id = :g"
            ),
            {"g": gid},
        )
    assert client.get(f"/api/v1/invoices/{inv}", headers=oh).status_code == 404
    with pytest.raises(DBAPIError), session(w.tenant_id, app_engine) as s:  # never longer than 7 days
        s.execute(
            text("update support_grants set ends_at = starts_at + interval '8 days' where id = :g"),
            {"g": gid},
        )


# --- email intake, IT-12 ------------------------------------------------------------------------


def _post(client, payload: dict, key: bytes, ts: str | None = None, sig: str | None = None):  # type: ignore[no-untyped-def]
    body = json.dumps(payload).encode()
    ts = ts or str(int(time.time()))
    return client.post(
        "/api/v1/inbound/email",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-MatchDesk-Timestamp": ts,
            "X-MatchDesk-Signature": sig or sign(body, ts, key),
        },
    )


def test_it12_email_intake_signed_allowed_held_and_once(app_engine, client):  # type: ignore[no-untyped-def]
    settings = load_settings()
    key = signing_key(settings)
    w = make_tenant(app_engine, "Fictional Distributor EM01")
    _c, ctrl = add_user(app_engine, w, "controller")
    with global_session(app_engine) as s:
        s.execute(
            text("update tenants set intake_address_local = :l where id = :t"),
            {"l": f"em-{w.tenant_id.hex[:8]}", "t": str(w.tenant_id)},
        )
    to = f"em-{w.tenant_id.hex[:8]}@{settings.intake_domain}"
    pdf = text_pdf(["INVOICE", "Invoice No: EM-1", "Synthetic"], title="EM-1")
    att = [
        {"filename": "EM-1.pdf", "content_base64": base64.b64encode(pdf).decode()},
        {"filename": "notes.txt", "content_base64": base64.b64encode(b"hello").decode()},
    ]
    msg = {
        "message_id": "m-1",
        "from": "billing@supplier.example",
        "to": to,
        "subject": "Invoice",
        "attachments": att,
    }
    # Unsigned, wrongly signed or stale: refused, nothing stored.
    assert _post(client, msg, key, sig="0" * 64).status_code == 401
    assert _post(client, msg, key, ts=str(int(time.time()) - 3600)).status_code == 401
    assert _post(client, {**msg, "to": "nobody@" + settings.intake_domain}, key).status_code == 404
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(text("select count(*) from inbound_messages")) == 0
    # Unknown sender: held.
    r = _post(client, msg, key)
    assert r.status_code == 202 and r.json()["status"] == "held"
    assert _post(client, msg, key).json()["duplicate"] is True  # a retry is the same message
    # The controller allows the domain; the next message goes straight into a batch.
    assert (
        client.post(
            "/api/v1/intake/senders", json={"address_or_domain": "@supplier.example"}, headers=w.headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/intake/senders", json={"address_or_domain": "@supplier.example"}, headers=ctrl
        ).status_code
        == 201
    )
    r2 = _post(client, {**msg, "message_id": "m-2"}, key)
    assert r2.json()["status"] == "processed" and r2.json()["batch_id"]
    batch = client.get(f"/api/v1/intake/batches/{r2.json()['batch_id']}", headers=w.headers).json()
    assert batch["totals"]["file_count"] == 1  # the text file is not an invoice and is left out
    # The held one is released by the clerk into a batch too (same PDF: a duplicate file).
    held = [
        m
        for m in client.get("/api/v1/intake/email", headers=w.headers).json()["messages"]
        if m["status"] == "held"
    ]
    assert len(held) == 1
    rel = client.post(
        f"/api/v1/intake/messages/{held[0]['id']}/decision", json={"decision": "release"}, headers=w.headers
    )
    assert rel.status_code == 200 and rel.json()["status"] == "processed"
    again = client.post(
        f"/api/v1/intake/messages/{held[0]['id']}/decision", json={"decision": "discard"}, headers=w.headers
    )
    assert again.status_code == 409
