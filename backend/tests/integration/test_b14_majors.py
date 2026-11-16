"""B14 (2026-11-17): the Major findings of the independent acceptance test that live in the API.
M1 is a web finding (web/src/b14-acceptance.test.tsx, web/e2e/acceptance-b14.spec.ts). Synthetic data.

M2. A possible duplicate's money is in the queue total and the weekly open value once.
M3. Files the server refuses stay on their batch with the reason; the counts add up to the files chosen.
M4. The PDF export speaks the words of design.md section 9, names suppliers, fits the page, and
    carries the same figures as the screen.
M5. A new account gets its first user: the operator creates it and invites its first controller,
    who accepts and signs in.
"""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from matchdesk.api.app import create_app
from matchdesk.core import RecordingMailer, load_settings, text_pdf
from matchdesk.identity import User, enroll_operator, issue_session
from matchdesk.intake import sign, signing_key
from matchdesk.reporting import week_of
from matchdesk.reporting.backtest import PDF_WIDTH, TYPE_WORDS
from matchdesk.tenancy import global_session

from .b2_helpers import BASE_URL, token_from
from .b14_helpers import OCT, drain, exc_of, excs, match, second_supplier
from .seed import add_invoice, add_receipt, add_user, auth_headers, make_tenant

pytestmark = pytest.mark.integration
MAIL = RecordingMailer()


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(mailer=MAIL))


def make_operator(engine):  # type: ignore[no-untyped-def]
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        u = User(email=email, display_name="Synthetic Operator")
        s.add(u)
        s.flush()
        uid = u.id
    enroll_operator(engine, email)
    return uid, auth_headers(issue_session(engine, uid, None))


def pdf_lines(data: bytes) -> list[str]:
    """The text lines of a ``core.text_pdf`` document, as written (the draft mark left out)."""
    out = []
    for raw in re.findall(rb"\((.*)\) Tj T\*", data):
        s = raw.decode("latin-1")
        out.append(s.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\"))
    return out


# --- M2 ---------------------------------------------------------------------------------------------


def test_m2_a_possible_duplicate_is_counted_once_in_queue_and_weekly_open_value(app_engine, client):  # type: ignore[no-untyped-def]
    """FF-1010 of the acceptance test: the same total as another invoice 3 days earlier, and over
    received on its own line. The queue listed 105.00 twice (possible duplicate and the line)."""
    w = make_tenant(app_engine, "Fictional Distributor B14-M2")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "25", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "FF-1001", date(2026, 10, 5), "25")  # 105.00, received
    b = add_invoice(app_engine, w, "b", "FF-1010", date(2026, 10, 8), "25")  # 105.00 again
    match(client, app_engine, w.headers, [a, b])
    pd = exc_of(app_engine, w, b, "possible_duplicate")
    line = exc_of(app_engine, w, b, "qty_over_received")
    assert str(pd.variance_amount) == "105.00" and str(line.reported_amount) == "105.00"
    assert str(pd.reported_amount) == "0.00"  # the document's money is already counted on its line
    assert pd.value_class == "open_undecided" and not pd.qualifying
    q = client.get("/api/v1/exceptions", params={"status": "open", **OCT}, headers=w.headers).json()
    mine = [i for i in q["items"] if i["invoice_id"] == str(b)]
    assert len(mine) == 2 and q["total_count"] == 2
    assert q["total_value"] == "105.00"  # was 210.00
    assert D(q["total_value"]) == sum(D(i["reported_amount"]) for i in q["items"])
    week = client.get("/api/v1/weekly-summary", params={"week_start": "2026-10-05"}, headers=ctrl)
    assert week.status_code == 200, week.text
    assert week_of(date(2026, 10, 8)) == date(2026, 10, 5)
    total = week.json()["total"]
    assert (total["open_count"], total["open_value"]) == (2, "105.00")
    # The decision still counts the document once (verified working in the acceptance test).
    r = client.post(
        f"/api/v1/exceptions/{pd.id}/duplicate-decision",
        json={"decision": "is_duplicate"},
        headers={**ctrl, "If-Match": str(pd.version)},
    )
    assert r.status_code == 200, r.text
    drain(app_engine)
    q = client.get("/api/v1/exceptions", params={"status": "open", **OCT}, headers=w.headers).json()
    assert q["total_value"] == "105.00" and [i["type"] for i in q["items"]] == ["duplicate"]


def test_m2_a_possible_duplicate_with_clean_lines_still_shows_its_total(app_engine, client):  # type: ignore[no-untyped-def]
    """Where the lines report nothing, the whole total stays under the possible duplicate."""
    w = make_tenant(app_engine, "Fictional Distributor B14-M2b")
    add_receipt(app_engine, w, "50", date(2026, 9, 28))
    a = add_invoice(app_engine, w, "a", "FF-2001", date(2026, 10, 5), "25")
    b = add_invoice(app_engine, w, "b", "FF-2010", date(2026, 10, 8), "25")  # both fit the receipt
    match(client, app_engine, w.headers, [a, b])
    pd = exc_of(app_engine, w, b, "possible_duplicate")
    assert str(pd.reported_amount) == "105.00"
    q = client.get("/api/v1/exceptions", params={"status": "open", **OCT}, headers=w.headers).json()
    assert q["total_value"] == "105.00"


# --- M3 ---------------------------------------------------------------------------------------------


def _upload(client, w, batch, name, data, key):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/intake/batches/{batch}/files",
        files={"file": (name, data, "application/pdf")},
        headers={**w.headers, "Idempotency-Key": key},
    )


def test_m3_refused_files_stay_on_the_batch_with_the_reason(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-M3")
    batch = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    good = text_pdf(["INVOICE", "Invoice No: M3-1", "Synthetic"], title="M3-1")
    assert _upload(client, w, batch, "good.pdf", good, "k-good").status_code == 201
    junk = _upload(client, w, batch, "junk.pdf", b"this is not a PDF at all", "k-junk")
    assert junk.status_code == 415
    assert (
        _upload(client, w, batch, "junk.pdf", b"this is not a PDF at all", "k-junk").status_code == 415
    )  # a retry
    assert _upload(client, w, batch, "empty.pdf", b"", "k-empty").status_code == 415
    body = client.get(f"/api/v1/intake/batches/{batch}", headers=w.headers).json()
    assert [(r["name"], r["reason"], r["reason_words"]) for r in body["refused"]] == [
        ("junk.pdf", "not_supported", "Not a PDF, PNG or JPEG file"),
        ("empty.pdf", "empty", "The file is empty"),
    ]
    t = body["totals"]
    assert (t["file_count"], t["refused"]) == (1, 2) and len(body["files"]) == 1
    states = sum(v for k, v in t.items() if k not in ("file_count", "refused"))
    assert states == t["file_count"]  # IT-07: the states still sum to the files stored
    listed = client.get("/api/v1/intake/batches", headers=w.headers).json()["items"]
    assert next(b for b in listed if b["id"] == batch)["totals"]["refused"] == 2
    # A batch of refused files only is never an empty, "everything read" batch.
    only = client.post("/api/v1/intake/batches", headers=w.headers).json()["id"]
    assert _upload(client, w, only, "junk2.pdf", b"GIF89a not accepted", "k-j2").status_code == 415
    t = client.get(f"/api/v1/intake/batches/{only}", headers=w.headers).json()["totals"]
    assert (t["file_count"], t["refused"]) == (0, 1)
    # A file over the size limit never reaches the server; the browser reports it by name.
    big = client.post(
        f"/api/v1/intake/batches/{only}/refusals",
        json={"name": "huge.pdf", "byte_size": 30 * 1024 * 1024},
        headers={**w.headers, "Idempotency-Key": "k-big"},
    )
    assert big.status_code == 201, big.text
    small = client.post(
        f"/api/v1/intake/batches/{only}/refusals",
        json={"name": "small.pdf", "byte_size": 10},
        headers={**w.headers, "Idempotency-Key": "k-small"},
    )
    assert small.status_code == 422  # only a file over the limit is taken on the client's word
    refused = client.get(f"/api/v1/intake/batches/{only}", headers=w.headers).json()["refused"]
    assert [(r["name"], r["reason"]) for r in refused] == [
        ("junk2.pdf", "not_supported"),
        ("huge.pdf", "too_large"),
    ]
    # Tenant boundary and role: another account's batch is not found; a viewer may not record.
    other = make_tenant(app_engine, "Fictional Distributor B14-M3x")
    assert _upload(client, other, batch, "junk.pdf", b"nope", "k-x").status_code == 404
    _v, viewer = add_user(app_engine, w, "viewer")
    assert (
        client.post(
            f"/api/v1/intake/batches/{only}/refusals",
            json={"name": "v.pdf", "byte_size": 30 * 1024 * 1024},
            headers={**viewer, "Idempotency-Key": "k-v"},
        ).status_code
        == 403
    )


def test_m3_an_email_with_no_usable_attachment_is_not_an_invoice_received(app_engine, client):  # type: ignore[no-untyped-def]
    settings = load_settings()
    key = signing_key(settings)
    w = make_tenant(app_engine, "Fictional Distributor B14-M3e")
    _c, ctrl = add_user(app_engine, w, "controller")
    local = f"m3-{w.tenant_id.hex[:8]}"
    with global_session(app_engine) as s:
        s.execute(
            text("update tenants set intake_address_local = :l where id = :t"),
            {"l": local, "t": str(w.tenant_id)},
        )
    assert (
        client.post(
            "/api/v1/intake/senders", json={"address_or_domain": "@supplier.example"}, headers=ctrl
        ).status_code
        == 201
    )
    payload = {
        "message_id": f"m3-{uuid.uuid4().hex}",
        "from": "billing@supplier.example",
        "to": f"{local}@{settings.intake_domain}",
        "subject": "Invoice",
        "attachments": [{"filename": "notes.txt", "content_base64": base64.b64encode(b"hello").decode()}],
    }
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    r = client.post(
        "/api/v1/inbound/email",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-MatchDesk-Timestamp": ts,
            "X-MatchDesk-Signature": sign(body, ts, key),
        },
    )
    assert r.status_code == 202, r.text
    msg = client.get("/api/v1/intake/email", headers=w.headers).json()["messages"][0]
    assert (msg["status"], msg["files_read"], msg["files_refused"]) == ("processed", 0, 1)
    batch = client.get(f"/api/v1/intake/batches/{msg['batch_id']}", headers=w.headers).json()
    assert batch["totals"]["file_count"] == 0
    assert [(x["name"], x["reason"]) for x in batch["refused"]] == [("notes.txt", "not_supported")]


# --- M4 ---------------------------------------------------------------------------------------------


def test_m4_pdf_uses_the_screen_words_names_suppliers_fits_the_page_and_equals_the_screen(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B14-M4")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "60", date(2026, 9, 28))
    add_invoice(app_engine, w, "a", "FF-1002", date(2026, 10, 2), "60")
    add_invoice(app_engine, w, "b", "FF-1003", date(2026, 10, 9), "40", price="4.50")  # over received, price
    long_name = "Synthetic Supplier With A Very Long Registered Company Name Incorporated " * 3
    w2 = second_supplier(app_engine, w)
    from matchdesk.qbo.models import Vendor
    from matchdesk.tenancy import session

    with session(w.tenant_id, app_engine) as s:
        s.get(Vendor, w2.vendor_id).name = long_name.strip()  # type: ignore[union-attr]
    add_invoice(app_engine, w2, "c", "IP-302", date(2026, 10, 12), "10")  # no receipt: receipt absent
    match(client, app_engine, w.headers, list(w.invoices.values()))
    d = client.post("/api/v1/reports/backtest", json=OCT, headers=ctrl).json()
    full = client.get(f"/api/v1/reports/backtest/{d['id']}", headers=ctrl).json()
    assert full["findings"], "the scenario must list something"
    pdf = client.get(f"/api/v1/reports/backtest/{d['id']}/export?format=pdf", headers=ctrl)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    lines = pdf_lines(pdf.content)
    text_all = "\n".join(lines)
    # 1. Not clipped: no line is wider than the page.
    assert max(len(ln) for ln in lines) <= PDF_WIDTH
    # 2. Words, never codes: no internal code with an underscore, no raw timestamp.
    assert not re.search(r"\b[a-z]+_[a-z_]+\b", text_all), re.findall(r"\b[a-z]+_[a-z_]+\b", text_all)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:", text_all)
    for f in full["findings"]:
        assert TYPE_WORDS[f["type"]] in text_all
    assert "Draft, not approved" in text_all and "Pacific time" in text_all
    # 3. Suppliers: every supplier of a listed row, the long one whole (wrapped, not cut).
    assert "Fictional Supplier T" in text_all
    assert text_all.count("Incorporated") == 3 and text_all.count("Registered") == 3  # every word, wrapped

    # 4. The same figures as the screen (the API the screen reads).
    def figure(label: str) -> str:
        row = next(ln for ln in lines if ln.strip().startswith(label))
        return row.split()[-1]

    assert figure("Flagged discrepancies") == full["flagged_amount"]
    assert figure("Findings") == full["findings_amount"]
    assert figure("Not received") == full["not_received_amount"]
    assert figure("Unverified") == full["unverified_amount"]
    assert figure("Qualifying total for the refund") == full["qualifying_amount"]
    listed = sorted(D(f["amount"]) for f in full["findings"])
    in_pdf = sorted(
        D(m.group(1))
        for ln in lines
        if (m := re.search(r"\s(-?\d+\.\d{2})\s{2}(Already paid|Not yet paid|Not known)$", ln))
    )
    assert in_pdf == listed
    # 5. Approved: approver, account and the refund statement of the pilot.
    assert client.post(f"/api/v1/reports/backtest/{d['id']}/approve", headers=ctrl).status_code == 200
    approved = "\n".join(
        pdf_lines(client.get(f"/api/v1/reports/backtest/{d['id']}/export?format=pdf", headers=ctrl).content)
    )
    assert (
        "Approved by Synthetic controller" in approved and "Account: Fictional Distributor B14-M4" in approved
    )
    assert "Draft" not in approved


# --- M5 ---------------------------------------------------------------------------------------------


def test_m5_operator_creates_an_account_and_its_first_controller_signs_in(app_engine, client):  # type: ignore[no-untyped-def]
    op_id, oh = make_operator(app_engine)
    name = f"Fictional Newco {uuid.uuid4().hex[:6]}"
    email = f"first.{uuid.uuid4().hex[:8]}@example.invalid"
    made = client.post("/api/v1/operator/tenants", json={"name": name, "controller_email": email}, headers=oh)
    assert made.status_code == 201, made.text
    tid = made.json()["id"]
    assert made.json()["first_controller"] == {
        "has_controller": False,
        "invitations": [
            {"email": email, "expires_at": made.json()["first_controller"]["invitations"][0]["expires_at"]}
        ],
    }
    # m1: the same name again (a double press) is refused; one account exists.
    again = client.post("/api/v1/operator/tenants", json={"name": f"  {name.upper()} "}, headers=oh)
    assert again.status_code == 409 and "already exists" in again.text
    rows = client.get("/api/v1/operator/tenants", headers=oh).json()["items"]
    assert len([t for t in rows if t["name"] == name]) == 1
    # The invitation is in the mail, for a controller, and is the only way in.
    mail = next(m for m in reversed(MAIL.sent) if m.to == email)
    assert name in mail.subject and "as controller" in mail.body
    browser = TestClient(create_app(mailer=RecordingMailer()), base_url=BASE_URL)
    accepted = browser.post("/api/v1/invitations/accept", json={"token": token_from(mail.body, "/invite")})
    assert accepted.status_code == 201, accepted.text
    me = browser.get("/api/v1/me").json()
    assert me["role"] == "controller" and me["user"]["email"] == email
    assert [m["tenant_name"] for m in me["memberships"]] == [name]
    # The first controller works at once: invites a clerk, reads the (empty) queue.
    csrf = {"X-CSRF-Token": me["csrf_token"]}
    clerk = browser.post(
        "/api/v1/invitations",
        json={"email": f"c.{uuid.uuid4().hex[:6]}@example.invalid", "role": "clerk"},
        headers=csrf,
    )
    assert clerk.status_code == 201, clerk.text
    assert browser.get("/api/v1/exceptions").json()["total_count"] == 0
    # A later sign-in by emailed link works like any member's.
    rec = RecordingMailer()
    later = TestClient(create_app(mailer=rec), base_url=BASE_URL)
    assert later.post("/api/v1/auth/login-links", json={"email": email}).status_code == 202
    signed = later.post("/api/v1/auth/sessions", json={"token": token_from(rec.sent[-1].body)})
    assert signed.status_code == 201 and later.get("/api/v1/me").json()["role"] == "controller"
    # From now on the operator has no part in the account's users, and still sees none of its data.
    state = client.get(f"/api/v1/operator/tenants/{tid}", headers=oh).json()["first_controller"]
    assert state == {"has_controller": True, "invitations": []}
    refused = client.post(
        f"/api/v1/operator/tenants/{tid}/controller-invitations",
        json={"email": "x@example.invalid"},
        headers=oh,
    )
    assert refused.status_code == 409
    assert client.get("/api/v1/exceptions", headers=oh).status_code in (401, 403, 404)
    # The account's audit log names the operator as the one who invited.
    audit = browser.get("/api/v1/audit-events").json()["items"]
    created = next(a for a in audit if a["action"] == "invitation_created" and a["actor_type"] == "operator")
    assert created["actor_user_id"] == str(op_id)


def test_m5_invite_later_replace_and_refusals(app_engine, client):  # type: ignore[no-untyped-def]
    _op, oh = make_operator(app_engine)
    name = f"Fictional Laterco {uuid.uuid4().hex[:6]}"
    made = client.post("/api/v1/operator/tenants", json={"name": name}, headers=oh)
    assert made.status_code == 201 and made.json()["first_controller"] == {
        "has_controller": False,
        "invitations": [],
    }
    tid = made.json()["id"]
    url = f"/api/v1/operator/tenants/{tid}/controller-invitations"
    a, b = (f"{x}.{uuid.uuid4().hex[:6]}@example.invalid" for x in "ab")
    assert client.post(url, json={"email": a}, headers=oh).status_code == 201
    first = next(m for m in reversed(MAIL.sent) if m.to == a)
    again = client.post(url, json={"email": a}, headers=oh)  # sent again: replaces, never piles up
    assert again.status_code == 201 and [i["email"] for i in again.json()["invitations"]] == [a]
    both = client.post(url, json={"email": b}, headers=oh).json()
    assert [i["email"] for i in both["invitations"]] == [a, b]
    stale = TestClient(create_app(mailer=RecordingMailer()), base_url=BASE_URL)
    assert (
        stale.post(
            "/api/v1/invitations/accept", json={"token": token_from(first.body, "/invite")}
        ).status_code
        == 400
    )
    # Not an operator: the console does not exist. Bad address: refused. Unknown account: not found.
    w = make_tenant(app_engine, "Fictional Distributor B14-M5x", role="controller")
    assert client.post(url, json={"email": a}, headers=w.headers).status_code == 404
    assert client.post(url, json={"email": "not-an-address"}, headers=oh).status_code == 422
    assert (
        client.post(
            f"/api/v1/operator/tenants/{uuid.uuid4()}/controller-invitations", json={"email": a}, headers=oh
        ).status_code
        == 404
    )
    assert excs  # helper kept in use for readers of this module
