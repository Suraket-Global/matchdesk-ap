"""B10 (2026-11-13): the outside deep-QA findings on main 7206efb. All data synthetic.

Group 1: archive completeness (item 1) and deletion claim versus cancellation (item 2).
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk import blobstore
from matchdesk.api.app import create_app
from matchdesk.core import ConflictError
from matchdesk.identity import Tenant, User, enroll_operator, issue_session
from matchdesk.intake.models import DocumentRow
from matchdesk.qbo import FakeIntuitTokenEndpoint
from matchdesk.reporting import cancel_deletion, claim_due_deletions, execute_due_deletions
from matchdesk.reporting.models import ArchiveExport, DeletionRequest
from matchdesk.tenancy import global_session, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_user, auth_headers, make_tenant

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
    removed: list[str] = []
    monkeypatch.setattr(blobstore, "delete", lambda _t, k: removed.append(k))
    assert w.tenant_id not in execute_due_deletions(app_engine)
    assert removed == []
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(select(ArchiveExport.id).limit(1)) is None
        assert s.scalar(text("select count(*) from documents")) >= 1
