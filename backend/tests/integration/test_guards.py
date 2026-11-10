"""IT-24: the database refuses audit changes, a matched row with no receipt, and bad receipt_absent states."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from matchdesk.audit import write_audit
from matchdesk.exceptions import request_run
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def world(app_engine):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Guard tenant")
    add_invoice(app_engine, w, "inv", "INV-1", date(2026, 10, 4), "100")
    with session(w.tenant_id, app_engine) as s:
        write_audit(s, w.tenant_id, actor_type="system", action="test", entity_type="tenant")
        request_run(s, w.tenant_id, [w.invoices["inv"]])
    while run_once(app_engine):
        pass
    return w


def _refused(engine, tenant_id, sql, params=None):  # type: ignore[no-untyped-def]
    with pytest.raises(DBAPIError), session(tenant_id, engine) as s:
        s.execute(text(sql), params or {})


def test_it24_audit_events_are_insert_only(app_engine, world):  # type: ignore[no-untyped-def]
    _refused(app_engine, world.tenant_id, "update audit_events set action = 'x'")
    _refused(app_engine, world.tenant_id, "delete from audit_events")
    _refused(app_engine, world.tenant_id, "delete from exception_events")


def test_it24_matched_row_with_zero_receipt_lines_is_refused(app_engine, world):  # type: ignore[no-untyped-def]
    with session(world.tenant_id, app_engine) as s:
        lm = s.execute(text("select match_run_id, invoice_line_id from line_matches limit 1")).one()
    _refused(
        app_engine,
        world.tenant_id,
        "insert into line_matches (tenant_id, match_run_id, invoice_line_id, line_kind, po_line_id, alias_id, "
        "status, receipt_line_count, checks_run, is_current) values (:t, :r, :l, 'item', :p, :a, 'matched', 0, "
        "'{}', false)",
        {
            "t": str(world.tenant_id),
            "r": str(lm[0]),
            "l": str(lm[1]),
            "p": str(world.po_line_id),
            "a": str(world.alias_id),
        },
    )


def test_it24_line_match_status_cannot_be_updated(app_engine, world):  # type: ignore[no-untyped-def]
    _refused(
        app_engine, world.tenant_id, "update line_matches set status = 'matched', receipt_line_count = 1"
    )


def test_it24_receipt_absent_cannot_become_overbilling(app_engine, world):  # type: ignore[no-untyped-def]
    with session(world.tenant_id, app_engine) as s:
        exc = s.execute(text("select id from exceptions where type = 'receipt_absent'")).scalar()
    assert exc is not None
    _refused(
        app_engine,
        world.tenant_id,
        "update exceptions set resolution_code = 'confirmed_overbilling', status = 'resolved' where id = :i",
        {"i": str(exc)},
    )
    _refused(
        app_engine,
        world.tenant_id,
        "update exceptions set value_class = 'finding_candidate' where id = :i",
        {"i": str(exc)},
    )


def test_receipt_absent_cannot_link_to_a_matched_result(app_engine, world):  # type: ignore[no-untyped-def]
    # Build a legitimately matched row in a second tenant-run, then try to point receipt_absent at it.
    from .seed import add_receipt

    w2 = make_tenant(app_engine, "Guard tenant 2")
    add_invoice(app_engine, w2, "inv", "INV-1", date(2026, 10, 4), "100")
    add_receipt(app_engine, w2, "100", date(2026, 10, 3))
    with session(w2.tenant_id, app_engine) as s:
        request_run(s, w2.tenant_id, [w2.invoices["inv"]])
    while run_once(app_engine):
        pass
    with session(w2.tenant_id, app_engine) as s:
        matched = s.execute(
            text("select id, invoice_line_id from line_matches where status = 'matched'")
        ).one()
    _refused(
        app_engine,
        w2.tenant_id,
        "insert into exceptions (tenant_id, fingerprint, invoice_id, invoice_line_id, line_match_id, type, "
        "sub_reason, value_class) values (:t, :f, :i, :l, :m, 'receipt_absent', 'no_evidence', 'unverified')",
        {
            "t": str(w2.tenant_id),
            "f": uuid.uuid4().bytes,
            "i": str(w2.invoices["inv"]),
            "l": str(matched[1]),
            "m": str(matched[0]),
        },
    )


def test_tolerance_has_no_receipt_column_and_rules_cannot_overlap(app_engine, world):  # type: ignore[no-untyped-def]
    with session(world.tenant_id, app_engine) as s:
        cols = {
            r[0]
            for r in s.execute(
                text(
                    "select column_name from information_schema.columns where table_name = 'tolerance_rules'"
                )
            )
        }
        assert not any("receipt" in c for c in cols)
        s.execute(
            text("insert into tolerance_rules (tenant_id, valid_from, created_by) values (:t, now(), :u)"),
            {"t": str(world.tenant_id), "u": str(world.user_id)},
        )
    _refused(
        app_engine,
        world.tenant_id,
        "insert into tolerance_rules (tenant_id, valid_from, created_by) values (:t, now(), :u)",
        {"t": str(world.tenant_id), "u": str(world.user_id)},
    )
