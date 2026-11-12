"""IT-01, IT-02, IT-03, IT-29 (partial), RLS catalogue checks."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from matchdesk import blobstore
from matchdesk.api.app import create_app
from matchdesk.core import NotFoundError
from matchdesk.exceptions import execute_run
from matchdesk.schema_registry import GLOBAL_TABLES, load_all_models
from matchdesk.tenancy import claim, enqueue_raw, global_session, operator_session, run_claimed, session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, make_tenant

pytestmark = pytest.mark.integration
TENANT_TABLES = sorted(t for t in load_all_models().metadata.tables if t not in GLOBAL_TABLES)


@pytest.fixture(scope="module")
def two_tenants(app_engine):  # type: ignore[no-untyped-def]
    a = make_tenant(app_engine, "Fictional Distributor A")
    b = make_tenant(app_engine, "Fictional Distributor B")
    for w in (a, b):
        add_invoice(app_engine, w, "inv", "INV-01042", date(2026, 10, 4), "100")
        add_receipt(app_engine, w, "60", date(2026, 10, 3))
    client = TestClient(create_app())
    # Run a match in B so B has match runs, line matches and exceptions too.
    r = client.post(
        "/api/v1/match-runs",
        json={"invoice_ids": [str(b.invoices["inv"])]},
        headers=b.headers,
    )
    assert r.status_code == 202, r.text
    while run_once(app_engine):
        pass
    return a, b, client, r.json()["id"]


def test_app_role_cannot_bypass_rls(app_engine):  # type: ignore[no-untyped-def]
    with global_session(app_engine) as s:
        row = s.execute(
            text("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        ).one()
    assert tuple(row) == (False, False)


def test_every_tenant_table_has_forced_rls_and_only_allowed_policies(owner_engine):  # type: ignore[no-untyped-def]
    with owner_engine.connect() as c:
        rows = c.execute(
            text(
                "select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "(select string_agg(p.policyname, ',' order by p.policyname) from pg_policies p "
                "where p.tablename = c.relname) "
                "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = 'public' and c.relkind = 'r'"
            )
        ).all()
    catalogue = {r[0]: r[1:] for r in rows}
    # Exactly the tenant policy, plus the read-only lookup policies of B2 (schema.md 9.1).
    expected = {
        "memberships": "membership_self,tenant_isolation",
        "invitations": "invitation_by_token,tenant_isolation",
        # B7: the operator allow-list of schema.md 4.3, exactly these three tables.
        "pilot_engagements": "operator_insert,operator_select,operator_update,tenant_isolation",
        "usage_events": "operator_select,tenant_isolation",
        "support_grants": "operator_insert,operator_select,tenant_isolation",
    }
    for table in TENANT_TABLES:
        assert catalogue[table] == (True, True, expected.get(table, "tenant_isolation")), table
    unprotected = {t for t, (rls, _f, _n) in catalogue.items() if not rls}
    assert unprotected <= GLOBAL_TABLES, unprotected - GLOBAL_TABLES


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_no_tenant_context_reads_zero_rows(app_engine, two_tenants, table):  # type: ignore[no-untyped-def]
    a, _b, _c, _r = two_tenants
    with global_session(app_engine) as s:
        assert s.execute(text(f"select count(*) from {table}")).scalar() == 0  # noqa: S608
    with session(a.tenant_id, app_engine) as s:
        other = s.execute(
            text(f"select count(*) from {table} where tenant_id <> :a"),  # noqa: S608
            {"a": str(a.tenant_id)},
        ).scalar()
        assert other == 0


def test_tables_with_rows_in_both_tenants(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, b, _c, _r = two_tenants
    for tid in (a.tenant_id, b.tenant_id):
        with session(tid, app_engine) as s:
            for table in ("invoices", "invoice_lines", "receipt_lines", "documents", "item_aliases"):
                assert s.execute(text(f"select count(*) from {table}")).scalar() > 0  # noqa: S608


def test_insert_without_tenant_context_is_refused(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, *_ = two_tenants
    with pytest.raises(DBAPIError), global_session(app_engine) as s:
        s.execute(
            text("insert into vendors (tenant_id, qbo_id, name, synced_at) values (:t, 'X', 'x', now())"),
            {"t": str(a.tenant_id)},
        )


def test_composite_fk_blocks_cross_tenant_reference(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, b, *_ = two_tenants
    with pytest.raises(IntegrityError), session(a.tenant_id, app_engine) as s:
        s.execute(
            text(
                "insert into purchase_orders (tenant_id, qbo_id, vendor_id, po_number, po_number_norm, "
                "txn_date, synced_at) values (:a, 'POX', :bv, '1', '1', '2026-09-01', now())"
            ),
            {"a": str(a.tenant_id), "bv": str(b.vendor_id)},
        )


def test_it01_cross_tenant_requests_return_404(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, b, client, b_run = two_tenants
    h = a.headers
    with session(b.tenant_id, app_engine) as s:
        b_exc = s.execute(text("select id from exceptions limit 1")).scalar()
        before = s.execute(text("select count(*), max(version) from exceptions")).one()
    assert b_exc is not None
    for path in (
        f"/api/v1/match-runs/{b_run}",
        f"/api/v1/invoices/{b.invoices['inv']}",
        f"/api/v1/exceptions/{b_exc}",
        f"/api/v1/documents/{b.documents['inv']}/content",
    ):
        r = client.get(path, headers=h)
        assert r.status_code == 404, path
        assert str(b.tenant_id) not in r.text and "INV-01042" not in r.text
    r = client.post("/api/v1/match-runs", json={"invoice_ids": [str(b.invoices["inv"])]}, headers=h)
    assert r.status_code == 404
    # A missing record looks exactly the same.
    missing = client.get(f"/api/v1/match-runs/{uuid.uuid4()}", headers=h)
    assert missing.status_code == 404 and missing.json()["title"] == "Not found"
    with session(b.tenant_id, app_engine) as s:
        assert s.execute(text("select count(*), max(version) from exceptions")).one() == before
    # Own records are visible.
    own = client.get(f"/api/v1/invoices/{a.invoices['inv']}", headers=h)
    assert own.status_code == 200
    assert client.get("/api/v1/match-runs/" + b_run).status_code == 401


def test_it02_job_without_tenant_is_rejected_and_job_sees_only_its_tenant(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, b, *_ = two_tenants
    with global_session(app_engine) as s:
        enqueue_raw(s, "match_run", {"match_run_id": str(uuid.uuid4())})
    job = claim(engine=app_engine)
    assert job is not None
    assert run_claimed(job, {"match_run": execute_run}, app_engine) == "failed"
    with global_session(app_engine) as s:
        err = s.execute(text("select last_error from job_queue where id = :i"), {"i": str(job.id)}).scalar()
    assert err == "missing tenant_id"

    seen: dict[str, object] = {}

    def spy(s, payload):  # type: ignore[no-untyped-def]
        seen["tenants"] = {r[0] for r in s.execute(text("select distinct tenant_id from invoices"))}

    with global_session(app_engine) as s:
        enqueue_raw(s, "spy", {"tenant_id": str(a.tenant_id)})
    job = claim(engine=app_engine)
    assert job is not None and run_claimed(job, {"spy": spy}, app_engine) == "succeeded"
    assert seen["tenants"] == {a.tenant_id}
    # B's match run payload executed with A's tenant finds nothing.
    with global_session(app_engine) as s:
        b_run = s.execute(
            text(
                "select payload->>'match_run_id' from job_queue where task='match_run' "
                "and payload->>'tenant_id' = :b"
            ),
            {"b": str(b.tenant_id)},
        ).scalar()
        enqueue_raw(s, "match_run", {"tenant_id": str(a.tenant_id), "match_run_id": b_run})
    job = claim(engine=app_engine)
    assert job is not None and run_claimed(job, {"match_run": execute_run}, app_engine) == "failed"


def test_it03_blobstore_refuses_other_tenant_keys(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    a, b, _client, _ = two_tenants
    b_key = blobstore.build_key(b.tenant_id, "invoice", b"x")
    with pytest.raises(blobstore.BlobKeyError):
        blobstore.put(a.tenant_id, b_key, b"x")
    with pytest.raises(NotFoundError):
        blobstore.get(a.tenant_id, b_key)
    with pytest.raises(blobstore.BlobKeyError):
        blobstore.put(a.tenant_id, f"t/{a.tenant_id}/../{b.tenant_id}/invoice/x", b"x")
    # The database refuses a document row whose key is outside its tenant.
    with pytest.raises(IntegrityError), session(a.tenant_id, app_engine) as s:
        s.execute(
            text(
                "insert into documents (tenant_id, purpose, source, blob_key, sha256, mime_type, byte_size,"
                " correlation_id) values (:a, 'invoice', 'upload', :k, '\\x00', 'application/pdf', 1,"
                " gen_random_uuid())"
            ),
            {"a": str(a.tenant_id), "k": b_key},
        )


OPERATOR_READABLE = {"pilot_engagements", "usage_events", "support_grants"}  # schema.md 4.3


def test_it29_operator_without_grant_sees_no_tenant_row(app_engine, two_tenants):  # type: ignore[no-untyped-def]
    with operator_session(app_engine) as s:
        for table in TENANT_TABLES:
            if table in OPERATOR_READABLE:
                continue  # pilot terms, billable units and grants only: no document, price or line
            assert s.execute(text(f"select count(*) from {table}")).scalar() == 0, table  # noqa: S608
