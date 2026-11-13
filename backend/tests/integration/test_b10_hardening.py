"""B10 (2026-11-13): the outside deep-QA findings on main 7206efb. All data synthetic.

Group 1: archive completeness (item 1) and deletion claim versus cancellation (item 2).
Group 3: weekly delivery per recipient (5), the unmeasured week's words (6), job claim attempts (7)
and independent scheduled operations (8).
"""

from __future__ import annotations

import hashlib
import io
import random
import uuid
import zipfile
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk import blobstore
from matchdesk.api.app import create_app
from matchdesk.core import ConflictError, OutgoingMail, load_settings
from matchdesk.identity import Tenant, User, enroll_operator, issue_session
from matchdesk.intake.models import DocumentRow, InvoiceRow
from matchdesk.qbo import FakeIntuitTokenEndpoint
from matchdesk.receiving.models import ReceivingImportRow
from matchdesk.reporting import (
    cancel_deletion,
    claim_due_deletions,
    execute_due_deletions,
    last_sent,
    send_weekly,
)
from matchdesk.reporting.models import ArchiveExport, BacktestReport, DeletionRequest
from matchdesk.reporting.weekly import recipients as reporting_recipients
from matchdesk.tenancy import PermanentJobError, claim, enqueue_raw, global_session, run_claimed, session
from matchdesk.worker import __main__ as worker_main
from matchdesk.worker.__main__ import run_once

from .seed import NOW, add_invoice, add_user, auth_headers, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app(qbo_token_endpoint=FakeIntuitTokenEndpoint()))


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def operator_headers(engine) -> dict[str, str]:  # type: ignore[no-untyped-def]
    email = f"op.{uuid.uuid4().hex[:8]}@example.invalid"
    with global_session(engine) as s:
        op = User(email=email, display_name="Synthetic Operator")
        s.add(op)
        s.flush()
        op_id = op.id
    enroll_operator(engine, email)
    return auth_headers(issue_session(engine, op_id, None))


REAL_GET = blobstore.get


def unreadable(failing_keys: set[str]):  # type: ignore[no-untyped-def]
    real = REAL_GET

    def get(tenant_id, key):  # type: ignore[no-untyped-def]
        if key in failing_keys:
            raise OSError("synthetic storage read error")
        return real(tenant_id, key)

    return get


# --- item 1: an archive with an unreadable original is incomplete, never ready ----------------------


def test_archive_with_unreadable_original_is_incomplete_and_retry_completes_it(
    app_engine, client, monkeypatch
):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-A1")
    _c, ctrl = add_user(app_engine, w, "controller")
    a = add_invoice(app_engine, w, "a1", "INV-B10A1", date(2026, 10, 6), "10")
    add_invoice(app_engine, w, "a2", "INV-B10A2", date(2026, 10, 7), "10")
    with session(w.tenant_id, app_engine) as s:
        doc_id = s.scalar(text("select document_id from invoices where id = :i"), {"i": str(a)})
        bad_key = s.scalar(select(DocumentRow.blob_key).where(DocumentRow.id == doc_id))
    monkeypatch.setattr(blobstore, "get", unreadable({bad_key}))
    r = client.post("/api/v1/exports/archive", headers=ctrl)
    assert r.status_code == 202
    drain(app_engine)
    got = client.get("/api/v1/exports/archive", headers=ctrl).json()["items"][0]
    assert got["status"] == "incomplete", got
    assert (got["expected_count"], got["included_count"], got["missing_count"]) == (2, 1, 1)
    assert got["complete"] is False
    z = client.get(f"/api/v1/exports/archive/{got['id']}/content", headers=ctrl)
    assert z.status_code == 200  # the partial archive is still downloadable, labelled incomplete
    readme = zipfile.ZipFile(io.BytesIO(z.content)).read("README.txt").decode()
    assert "INCOMPLETE: 1 of 2" in readme
    # The deletion dialog sees the incomplete state; a request without acknowledgement is refused.
    d = client.get("/api/v1/account/deletion-request", headers=ctrl).json()
    assert d["archive"] == {
        "state": "incomplete",
        "included": 1,
        "expected": 2,
        "checked_at": d["archive"]["checked_at"],
    }
    body = {"reason": "Pilot ended (synthetic)", "confirm_name": "Fictional Distributor B10-A1"}
    refused = client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl)
    assert refused.status_code == 409 and "incomplete (1 of 2 originals)" in refused.text
    # Retry: storage reads again; the archive becomes complete and replaces the earlier ZIP.
    monkeypatch.setattr(blobstore, "get", unreadable(set()))
    assert client.post(f"/api/v1/exports/archive/{got['id']}/retry", headers=ctrl).status_code == 202
    drain(app_engine)
    again = client.get("/api/v1/exports/archive", headers=ctrl).json()["items"][0]
    assert again["id"] == got["id"] and again["status"] == "ready" and again["complete"] is True
    assert (again["expected_count"], again["included_count"], again["missing_count"]) == (2, 2, 0)
    assert client.post(f"/api/v1/exports/archive/{got['id']}/retry", headers=ctrl).status_code == 409
    with session(w.tenant_id, app_engine) as s:
        zips = s.scalars(select(DocumentRow).where(DocumentRow.purpose == "export")).all()
        assert sum(1 for z_ in zips if z_.deleted_at is None) == 1
        actions = [r[0] for r in s.execute(text("select action from audit_events")).all()]
    assert {"archive.incomplete", "archive.retry_requested", "archive.ready"} <= set(actions)
    ok = client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl)
    assert ok.status_code == 201, ok.text
    assert ok.json()["request"]["archive"]["state"] == "complete"
    assert ok.json()["request"]["archive"]["acknowledged"] is False


def test_a_byte_identical_upload_is_the_earlier_file_not_a_missing_one(app_engine, client):  # type: ignore[no-untyped-def]
    """Found by Playwright on the B10 branch: the duplicate upload of the full flow stores no second
    copy, so counting it as an expected original made a complete archive read Incomplete 14/15."""
    w = make_tenant(app_engine, "Fictional Distributor B10-A3")
    _c, ctrl = add_user(app_engine, w, "controller")
    first = add_invoice(app_engine, w, "a3", "INV-B10A3", date(2026, 10, 6), "10")
    with session(w.tenant_id, app_engine) as s:
        doc = s.get(DocumentRow, s.scalar(text("select document_id from invoices where id = :i"), {"i": str(first)}))
        assert doc is not None
        s.add(
            DocumentRow(
                tenant_id=w.tenant_id,
                purpose="invoice",
                source="upload",
                blob_key=f"{doc.blob_key}/duplicate/{uuid.uuid4()}",  # as intake names it: never stored
                sha256=doc.sha256,
                mime_type=doc.mime_type,
                byte_size=doc.byte_size,
                state="duplicate_file",
                duplicate_of_document_id=doc.id,
                correlation_id=uuid.uuid4(),
            )
        )
    client.post("/api/v1/exports/archive", headers=ctrl)
    drain(app_engine)
    got = client.get("/api/v1/exports/archive", headers=ctrl).json()["items"][0]
    assert got["status"] == "ready" and (got["expected_count"], got["included_count"]) == (1, 1)
    z = client.get(f"/api/v1/exports/archive/{got['id']}/content", headers=ctrl)
    index = zipfile.ZipFile(io.BytesIO(z.content)).read("documents.csv").decode()
    assert f"same file as documents/{doc.id}.pdf" in index


def test_deletion_without_complete_archive_needs_acknowledgement_shown_to_operator(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-A2")
    _c, ctrl = add_user(app_engine, w, "controller")
    body = {"confirm_name": "Fictional Distributor B10-A2"}
    refused = client.post("/api/v1/account/deletion-requests", json=body, headers=ctrl)
    assert refused.status_code == 409 and "No archive" in refused.text
    ok = client.post(
        "/api/v1/account/deletion-requests",
        json={**body, "acknowledge_incomplete_archive": True},
        headers=ctrl,
    )
    assert ok.status_code == 201
    oh = operator_headers(app_engine)
    items = client.get("/api/v1/operator/deletion-requests", headers=oh).json()["items"]
    mine = next(i for i in items if i["id"] == ok.json()["request"]["id"])
    assert mine["archive"]["state"] == "none" and mine["archive"]["acknowledged"] is True
    # Item 15: the operator's row names the requesting controller.
    assert mine["requested_by_name"] == "Synthetic controller"


# --- item 2: the worker claims the deletion before the first file goes; cancelling is then refused ---


def _scheduled_due(app_engine, owner_engine, client, name):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, name)
    _c, ctrl = add_user(app_engine, w, "controller")
    add_invoice(app_engine, w, "d", f"INV-{name[-6:]}", date(2026, 10, 6), "10")
    rq = client.post(
        "/api/v1/account/deletion-requests",
        json={"confirm_name": name, "acknowledge_incomplete_archive": True},
        headers=ctrl,
    ).json()["request"]
    oh = operator_headers(app_engine)
    sched = client.post(
        f"/api/v1/operator/deletion-requests/{rq['id']}/decision",
        json={"decision": "schedule"},
        headers={**oh, "If-Match": str(rq["version"])},
    )
    assert sched.status_code == 200, sched.text
    with owner_engine.begin() as c:
        c.execute(
            text("update deletion_requests set delete_after = now() - interval '1 minute' where id = :i"),
            {"i": rq["id"]},
        )
    return w, ctrl, uuid.UUID(rq["id"])


def test_cancellation_during_file_removal_is_refused_and_the_deletion_finishes(
    app_engine, owner_engine, client, monkeypatch
):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _scheduled_due(app_engine, owner_engine, client, "Fictional Distributor B10-D1")
    real_delete = blobstore.delete
    seen: list[tuple[int, str]] = []

    def delete(tenant_id, key):  # type: ignore[no-untyped-def]
        if not seen:  # the controller presses Cancel just as the first file is removed
            with session(w.tenant_id, app_engine) as s:
                version = s.get(DeletionRequest, rid).version  # type: ignore[union-attr]
            r = client.post(
                f"/api/v1/account/deletion-requests/{rid}/cancel", headers={**ctrl, "If-Match": str(version)}
            )
            seen.append((r.status_code, r.text))
        real_delete(tenant_id, key)

    monkeypatch.setattr(blobstore, "delete", delete)
    assert w.tenant_id in execute_due_deletions(app_engine)
    assert seen and seen[0][0] == 409 and "already running" in seen[0][1], seen
    with global_session(app_engine) as s:
        assert s.get(Tenant, w.tenant_id) is None


def test_cancel_read_before_the_claim_cannot_win_after_it(app_engine, owner_engine, client):  # type: ignore[no-untyped-def]
    """Deterministic interleaving: the controller's transaction reads the request (scheduled), the
    worker's claim commits, then the controller's cancel runs. It must be refused."""
    w, ctrl, rid = _scheduled_due(app_engine, owner_engine, client, "Fictional Distributor B10-D2")
    with session(w.tenant_id, app_engine) as s:
        row = s.get(DeletionRequest, rid)
        assert row is not None and row.status == "scheduled"
        version, user = row.version, row.requested_by
        assert claim_due_deletions(app_engine) == [w.tenant_id]  # commits in its own transaction
        with pytest.raises(ConflictError, match="already running"):
            cancel_deletion(s, row, user, version)
    with session(w.tenant_id, app_engine) as s:
        assert s.get(DeletionRequest, rid).status == "deleting"  # type: ignore[union-attr]
    # The screens show Deleting; the request is not cancellable.
    got = client.get("/api/v1/account/deletion-request", headers=ctrl).json()["request"]
    assert got["status"] == "deleting" and got["cancellable"] is False
    # The next run resumes the claimed deletion only after the claim is stale; then it finishes.
    assert claim_due_deletions(app_engine) == []
    with owner_engine.begin() as c:
        c.execute(
            text("update deletion_requests set claimed_at = now() - interval '1 hour' where id = :i"),
            {"i": rid},
        )
    assert w.tenant_id in execute_due_deletions(app_engine)


def test_cancel_before_the_claim_wins_and_nothing_is_removed(app_engine, owner_engine, client, monkeypatch):  # type: ignore[no-untyped-def]
    w, ctrl, rid = _scheduled_due(app_engine, owner_engine, client, "Fictional Distributor B10-D3")
    with session(w.tenant_id, app_engine) as s:
        version = s.get(DeletionRequest, rid).version  # type: ignore[union-attr]
    r = client.post(
        f"/api/v1/account/deletion-requests/{rid}/cancel", headers={**ctrl, "If-Match": str(version)}
    )
    assert r.status_code == 200 and r.json()["request"]["status"] == "cancelled"
    removed: list[uuid.UUID] = []
    monkeypatch.setattr(blobstore, "delete", lambda t, _k: removed.append(t))
    assert w.tenant_id not in execute_due_deletions(app_engine)
    assert w.tenant_id not in removed  # other accounts due in this database may go; this one keeps every file
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(select(ArchiveExport.id).limit(1)) is None
        assert s.scalar(text("select count(*) from documents")) >= 1


# --- group 3: item 5, weekly email delivery per recipient ------------------------------------------


class FlakyMailer:
    """Fails for the addresses in ``down``; records the rest (synthetic)."""

    def __init__(self) -> None:
        self.down: set[str] = set()
        self.sent: list[OutgoingMail] = []

    def send(self, mail: OutgoingMail) -> None:
        if mail.to in self.down or "*" in self.down:
            raise ConnectionRefusedError("synthetic SMTP outage")
        self.sent.append(mail)


def _emails(engine, w) -> list[str]:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        return list(reporting_recipients(s))


def test_weekly_email_lost_after_a_mail_failure_is_sent_on_retry(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-W1")
    add_user(app_engine, w, "controller")
    add_user(app_engine, w, "controller")
    to = _emails(app_engine, w)
    assert len(to) == 2
    mailer = FlakyMailer()
    settings = load_settings()
    mailer.down = {"*"}
    first = send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "manual", mailer, settings)
    assert first is not None and first["sent"] == 0 and first["failed"] == 2
    with session(w.tenant_id, app_engine) as s:
        actions = [
            r[0] for r in s.execute(text("select action from audit_events order by occurred_at")).all()
        ]
    assert "weekly_summary.sent" not in actions and "weekly_summary.failed" in actions
    # One controller's mailbox is back: only the failed recipients are tried; one is delivered.
    mailer.down = {to[1]}
    second = send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "manual", mailer, settings)
    assert second is not None and (second["sent"], second["failed"]) == (1, 1)
    assert [m.to for m in mailer.sent] == [to[0]]
    mailer.down = set()
    third = send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "manual", mailer, settings)
    assert third is not None and (third["sent"], third["failed"], third["delivered_now"]) == (2, 0, 1)
    assert [m.to for m in mailer.sent] == [to[0], to[1]]  # nobody received it twice
    assert send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "manual", mailer, settings) is None
    with session(w.tenant_id, app_engine) as s:
        sent_events = s.execute(
            text("select after from audit_events where action = 'weekly_summary.sent' order by occurred_at")
        ).all()
        runs = last_sent(s)
    assert [e[0]["delivered_now"] for e in sent_events] == [1, 1]  # the audit says what was delivered
    assert runs[0]["delivered"] == 2 and runs[0]["failed"] == 0 and runs[0]["sent_at"] is not None


def test_send_now_retries_the_failed_recipients_of_the_scheduled_email(app_engine, client, monkeypatch):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-W2")
    _c, ctrl = add_user(app_engine, w, "controller")
    mailer = FlakyMailer()
    mailer.down = {"*"}
    send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "scheduled", mailer, load_settings())
    week = client.get("/api/v1/weekly-summary?week_start=2026-10-05", headers=ctrl).json()
    assert week["sent"][0]["failed"] == 1 and week["sent"][0]["sent_at"] is None
    assert week["sent"][0]["deliveries"][0]["state"] == "failed"
    # "Send now" retries that recipient (the app's mailer works), and creates no second email.
    r = client.post("/api/v1/weekly-summary/send", json={"week_start": "2026-10-05"}, headers=ctrl)
    assert r.status_code == 200, r.text
    assert r.json()["trigger"] == "scheduled" and r.json()["sent"] == 1 and r.json()["failed"] == 0


# --- item 6: an unmeasured week says so, in the email as on S-14 ------------------------------------


def test_empty_week_email_says_no_invoices_checked_not_cad_zero(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-W3")
    _c, ctrl = add_user(app_engine, w, "controller")
    mailer = FlakyMailer()
    run = send_weekly(app_engine, w.tenant_id, date(2026, 10, 5), "manual", mailer, load_settings())
    assert run is not None
    body = mailer.sent[0].body
    assert "No invoices checked for this week" in body
    assert "CAD 0.00" not in body and "Flagged discrepancies" not in body
    week = client.get("/api/v1/weekly-summary?week_start=2026-10-05", headers=ctrl).json()
    assert week["state"] == "awaiting_invoices"
    assert week["measurement"]["figures"] is False
    assert week["measurement"]["title"] == "No invoices checked for this week"
    assert week["measurement"]["text"] in body  # one rule, the same words


# --- item 7: a stale worker cannot overwrite a newer job result -------------------------------------


def test_expired_claim_late_failure_does_not_overwrite_a_success(app_engine):  # type: ignore[no-untyped-def]
    drain(app_engine)
    w = make_tenant(app_engine, "Fictional Distributor B10-J1")
    with global_session(app_engine) as s:
        job_id = enqueue_raw(s, "b10_probe", {"tenant_id": str(w.tenant_id)})
    a = claim(lease_seconds=0, engine=app_engine)  # worker A: its lease expires at once
    assert a is not None and a.id == job_id
    b = claim(lease_seconds=300, engine=app_engine)  # worker B takes the expired claim
    assert b is not None and b.id == job_id and b.attempts == a.attempts + 1

    def ok(_s, _p):  # type: ignore[no-untyped-def]
        return None

    def boom(_s, _p):  # type: ignore[no-untyped-def]
        raise PermanentJobError("synthetic late failure")

    assert run_claimed(b, {"b10_probe": ok}, app_engine) == "succeeded"
    assert run_claimed(a, {"b10_probe": boom}, app_engine) == "superseded"
    with global_session(app_engine) as s:
        state, err = s.execute(
            text("select state, last_error from job_queue where id = :i"), {"i": str(job_id)}
        ).one()
    assert (state, err) == ("succeeded", None)


# --- item 8: one failing scheduled operation does not block the others -----------------------------


def test_a_failing_weekly_email_does_not_stop_the_other_scheduled_operations(app_engine, client, monkeypatch):  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise ConnectionRefusedError("synthetic SMTP outage")

    def spy(name: str):  # type: ignore[no-untyped-def]
        def f(*_a, **_k):  # type: ignore[no-untyped-def]
            calls.append(name)
            return 0 if name != "due_deletions" else []

        return f

    monkeypatch.setattr(worker_main, "due_weekly", boom)
    monkeypatch.setattr(worker_main, "purge_raw", spy("raw_email_cleanup"))
    monkeypatch.setattr(worker_main, "purge_drafts_everywhere", spy("receiving_draft_cleanup"))
    monkeypatch.setattr(worker_main, "expire_archives", spy("archive_expiry"))
    monkeypatch.setattr(worker_main, "execute_due_deletions", spy("due_deletions"))
    done = worker_main.scheduled(app_engine, load_settings())
    assert calls == ["raw_email_cleanup", "receiving_draft_cleanup", "archive_expiry", "due_deletions"]
    assert done["weekly_summary"] is None
    oh = operator_headers(app_engine)
    items = client.get("/api/v1/operator/operations", headers=oh).json()["items"]
    assert items[0]["name"] == "weekly_summary" and items[0]["state"] == "failing"
    assert items[0]["last_error"] == "ConnectionRefusedError"
    ok = {i["name"]: i for i in items}
    assert ok["archive_expiry"]["state"] == "ok" and ok["archive_expiry"]["last_success_at"]
    # The next cycle succeeds: the failure count resets.
    monkeypatch.setattr(worker_main, "due_weekly", spy("weekly_summary"))
    worker_main.scheduled(app_engine, load_settings())
    items = client.get("/api/v1/operator/operations", headers=oh).json()["items"]
    assert all(i["state"] == "ok" for i in items)


# --- group 4: item 10, server-side order with a keyset cursor (201+ records) ------------------------


def _all_pages(client, headers, url: str, limit: int) -> list[dict]:  # type: ignore[no-untyped-def]
    items: list[dict] = []  # type: ignore[type-arg]
    cursor = None
    for _ in range(50):
        r = client.get(
            url, params={"limit": limit, **({"cursor": cursor} if cursor else {})}, headers=headers
        )
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        cursor = body["next_cursor"]
        if not cursor:
            return items
    raise AssertionError("paging did not end")


def _bulk_documents(s, w, n: int, purpose: str) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    ids = []
    for i in range(n):
        doc = DocumentRow(
            tenant_id=w.tenant_id,
            purpose=purpose,
            source="upload",
            blob_key=f"t/{w.tenant_id}/{purpose}/{uuid.uuid4().hex}",
            sha256=hashlib.sha256(f"{w.tenant_id}-{purpose}-{i}".encode()).digest(),
            mime_type="application/pdf" if purpose == "invoice" else "text/csv",
            byte_size=10,
            state="succeeded",
            correlation_id=uuid.uuid4(),
        )
        s.add(doc)
        s.flush()
        ids.append(doc.id)
    return ids


def test_invoices_page_in_document_date_order_across_201_plus(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-P1")
    rng = random.Random(10)
    days = [date(2026, 1, 1) + timedelta(days=rng.randrange(0, 300)) for _ in range(205)]
    with session(w.tenant_id, app_engine) as s:
        docs = _bulk_documents(s, w, len(days), "invoice")
        for i, (doc_id, d) in enumerate(zip(docs, days, strict=True)):
            s.add(
                InvoiceRow(
                    tenant_id=w.tenant_id,
                    document_id=doc_id,
                    file_order_key=hashlib.sha256(f"p1-{i}".encode()).digest(),
                    doc_type="invoice",
                    vendor_id=w.vendor_id,
                    doc_number=f"INV-P1-{i:03d}",
                    doc_number_norm=f"invp1{i:03d}",
                    doc_date=d,
                    currency="CAD",
                    verification_status="passed",
                )
            )
    for limit in (200, 37):
        got = _all_pages(client, w.headers, "/api/v1/invoices", limit)
        assert len(got) == 205 and len({g["id"] for g in got}) == 205
        keys = [(g["doc_date"], g["doc_number"], g["id"]) for g in got]
        assert keys == sorted(keys), "an older invoice appeared in a later page"


def test_reports_and_receiving_imports_page_in_display_order_across_201_plus(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor B10-P2")
    rng = random.Random(11)
    months = list(range(203))
    rng.shuffle(months)
    with session(w.tenant_id, app_engine) as s:
        for m in months:
            start = date(2000 + m // 12, m % 12 + 1, 1)
            s.add(
                BacktestReport(
                    tenant_id=w.tenant_id,
                    period_start=start,
                    period_end=start + timedelta(days=27),
                    version_no=1 + m % 2,
                    status="superseded",
                    data_cutoff_at=NOW,
                    totals={},
                )
            )
        docs = _bulk_documents(s, w, 204, "receiving")
        order = list(range(204))
        rng.shuffle(order)
        for i, doc_id in zip(order, docs, strict=True):
            s.add(
                ReceivingImportRow(
                    tenant_id=w.tenant_id,
                    source_type="spreadsheet",
                    evidence_class="A",
                    document_id=doc_id,
                    file_sha256=hashlib.sha256(f"p2-{i}".encode()).digest(),
                    state="voided",
                    created_at=NOW + timedelta(minutes=i // 2),  # pairs share a time: the id breaks it
                )
            )
    reports = _all_pages(client, w.headers, "/api/v1/reports/backtest", 200)
    assert len(reports) == 203
    rkeys = [(r["period_start"], r["version_no"]) for r in reports]
    assert rkeys == sorted(rkeys, reverse=True)
    imports = _all_pages(client, w.headers, "/api/v1/receiving/imports", 200)
    assert len(imports) == 204 and len({i["id"] for i in imports}) == 204
    ikeys = [(i["created_at"], i["id"]) for i in imports]
    assert ikeys == sorted(ikeys, reverse=True)
    assert (
        client.get("/api/v1/invoices", params={"cursor": "not-a-cursor"}, headers=w.headers).status_code
        == 422
    )
