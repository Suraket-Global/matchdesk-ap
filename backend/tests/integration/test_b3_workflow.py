"""B3 exception workflow, alias map and tolerances through the API: IT-13 (subset), IT-14, IT-15,
IT-21, IT-22, IT-23, IT-27, IT-28; tolerance versioning; alias suggestions; and the false-pass guard
that no resolution or bulk action turns a ``receipt_absent`` line into ``matched``."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from matchdesk.api.app import create_app
from matchdesk.exceptions.models import LineMatch, ToleranceRule
from matchdesk.tenancy import session
from matchdesk.worker.__main__ import run_once

from .seed import add_invoice, add_receipt, add_user, make_tenant

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(migrated):  # type: ignore[no-untyped-def]
    return TestClient(create_app())


def drain(engine) -> None:  # type: ignore[no-untyped-def]
    while run_once(engine):
        pass


def match(client, engine, headers, invoice_ids) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/match-runs", json={"invoice_ids": [str(i) for i in invoice_ids]}, headers=headers
    )
    assert r.status_code in (200, 202), r.text
    drain(engine)


def queue(client, headers, **params) -> list[dict]:  # type: ignore[no-untyped-def]
    return client.get("/api/v1/exceptions", params={"limit": 200, **params}, headers=headers).json()["items"]


def resolve(client, headers, e, code, note=None):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/exceptions/{e['id']}/resolutions",
        json={"code": code, "note": note},
        headers={**headers, "If-Match": str(e["version"])},
    )


def set_ordered(engine, w, qty: str) -> None:  # type: ignore[no-untyped-def]
    with session(w.tenant_id, engine) as s:
        s.execute(text("update po_lines set qty_ordered = :q"), {"q": qty})


def test_it22_bulk_waiver_skips_receipt_absent_and_it14_it23(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor W1")  # the clerk
    _cid, ctrl = add_user(app_engine, w, "controller")
    ids = [
        add_invoice(app_engine, w, f"a{i}", f"INV-A{i:03d}", date(2026, 10, 1 + i % 20), "1")
        for i in range(20)
    ]
    ids += [
        add_invoice(app_engine, w, f"p{i}", f"INV-P{i:03d}", date(2026, 10, 21), "1", price="4.50")
        for i in range(5)
    ]
    match(client, app_engine, w.headers, ids)
    absent = queue(client, w.headers, type="receipt_absent", status="open")
    pv = queue(client, w.headers, type="price_variance", status="open")
    assert len(absent) == 25 and len(pv) == 5
    target = [*absent[:20], *pv]
    r = client.post(
        "/api/v1/exceptions/bulk-resolutions",
        headers=w.headers,
        json={
            "items": [{"id": e["id"], "version": e["version"]} for e in target],
            "code": "waived",
            "note": "synthetic bulk waiver",
        },
    )
    assert r.status_code == 200, r.text
    results = {x["id"]: x for x in r.json()["results"]}
    assert all(results[e["id"]]["result"] == "skipped" for e in absent[:20])
    assert all(results[e["id"]]["result"] == "waived" for e in pv)  # 0.30 each: under limit and cap
    assert not queue(client, w.headers, type="receipt_absent", status="waived")
    with session(w.tenant_id, app_engine) as s:
        assert s.scalar(select(LineMatch).where(LineMatch.status == "matched")) is None
    # IT-14: two people resolve the same exception from the same version.
    e = absent[20]
    first = resolve(client, w.headers, e, "source_corrected")
    second = resolve(client, ctrl, e, "confirmed_not_received")
    assert first.status_code == 200 and second.status_code == 409
    assert second.json()["current"]["status"] == "resolved"
    # A clerk may not confirm "not received" (controller only).
    assert resolve(client, w.headers, absent[21], "confirmed_not_received").status_code == 403
    # IT-23: the controller reopens; the clerk cannot reopen another.
    cur = client.get(f"/api/v1/exceptions/{e['id']}", headers=w.headers).json()
    re_ = client.post(
        f"/api/v1/exceptions/{e['id']}/reopen", headers={**ctrl, "If-Match": str(cur["version"])}
    )
    assert re_.status_code == 200 and re_.json()["status"] == "open"
    events = client.get(f"/api/v1/exceptions/{e['id']}/events", headers=w.headers).json()["items"]
    reopened = [ev for ev in events if ev["event"] == "reopened"][-1]
    assert reopened["detail"]["previous"]["code"] == "source_corrected" and reopened["actor_user_id"] == str(
        _cid
    )
    other = queue(client, w.headers, type="price_variance", status="waived")[0]
    assert (
        client.post(
            f"/api/v1/exceptions/{other['id']}/reopen",
            headers={**w.headers, "If-Match": str(other["version"])},
        ).status_code
        == 403
    )
    # The controller confirms "not received": the decision changes the inputs and re-matches.
    cur = client.get(f"/api/v1/exceptions/{e['id']}", headers=w.headers).json()
    done = resolve(client, ctrl, cur, "confirmed_not_received")
    assert done.status_code == 200 and done.json()["match_run_id"]
    drain(app_engine)
    after = client.get(f"/api/v1/exceptions/{e['id']}", headers=w.headers).json()
    assert after["status"] == "resolved" and after["value_class"] == "finding_candidate"


def test_it27_waiver_limit_and_rolling_cap_singly_and_in_bulk(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor W2")  # clerk 1
    _k2, clerk2 = add_user(app_engine, w, "clerk")
    _c, ctrl = add_user(app_engine, w, "controller")
    set_ordered(app_engine, w, "100000")
    lim = client.put(
        "/api/v1/tolerances/default",
        json={"waiver_limit": "100.00", "waiver_period_cap": "500.00"},
        headers=ctrl,
    )
    assert lim.status_code == 200, lim.text
    prior = [
        add_invoice(app_engine, w, f"x{i}", f"INV-X{i}", date(2026, 10, 2), "100", price="5.16")
        for i in range(5)
    ]
    one = add_invoice(app_engine, w, "y", "INV-Y", date(2026, 10, 3), "100", price="4.50")
    ten = [
        add_invoice(app_engine, w, f"z{i}", f"INV-Z{i}", date(2026, 10, 4), "100", price="4.80")
        for i in range(10)
    ]
    big = add_invoice(app_engine, w, "big", "INV-BIG", date(2026, 10, 5), "100", price="6.00")
    match(client, app_engine, w.headers, [*prior, one, *ten, big])
    pv = {e["invoice_id"]: e for e in queue(client, w.headers, type="price_variance", status="open")}
    for inv in prior:  # 5 x 96.00 = 480.00 of unapproved waivers by clerk 1
        assert resolve(client, w.headers, pv[str(inv)], "waived", "synthetic").json()["result"] == "waived"
    r = resolve(client, w.headers, pv[str(one)], "waived", "synthetic")
    assert r.json()["result"] == "pending_approval" and r.json()["reason"] == "above_period_cap"
    r = resolve(client, w.headers, pv[str(big)], "waived", "synthetic")  # 180.00 > item limit
    assert r.json()["reason"] == "above_item_limit"
    bulk = client.post(
        "/api/v1/exceptions/bulk-resolutions",
        headers=clerk2,
        json={
            "items": [{"id": pv[str(i)]["id"], "version": pv[str(i)]["version"]} for i in ten],
            "code": "waived",
            "note": "synthetic",
        },
    )
    assert [x["result"] for x in bulk.json()["results"]] == ["pending_approval"] * 10  # 600.00 > cap
    pending = client.get("/api/v1/approvals", params={"subject_type": "waiver"}, headers=ctrl).json()["items"]
    assert len(pending) == 12
    assert client.get("/api/v1/approvals", headers=w.headers).status_code == 403  # a clerk cannot approve
    # The weekly list of waivers without approval: the queue filtered by status and date.
    waived = queue(client, ctrl, status="waived", resolved_since="2026-01-01T00:00:00+00:00")
    assert len(waived) == 5
    # The requester withdraws one of their own; the controller approves another.
    mine = next(a for a in pending if a["exception_id"] == pv[str(one)]["id"])
    cur = client.get(f"/api/v1/exceptions/{mine['exception_id']}", headers=w.headers).json()
    wd = client.post(
        f"/api/v1/exceptions/{cur['id']}/withdraw", headers={**w.headers, "If-Match": str(cur["version"])}
    )
    assert wd.status_code == 200 and wd.json()["status"] == "open"
    a = next(x for x in pending if x["exception_id"] == pv[str(big)]["id"])
    d = client.post(
        f"/api/v1/approvals/{a['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(a["version"])},
    )
    assert d.status_code == 200 and d.json()["effect"] == "waiver_applied"
    big_exc = client.get(f"/api/v1/exceptions/{a['exception_id']}", headers=w.headers).json()
    assert big_exc["status"] == "waived" and big_exc["qualifying"] is True  # a waiver never clears it


def test_it15_it21_alias_conversion_needs_approval_and_supersedes(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor W3")
    _c1, ctrl = add_user(app_engine, w, "controller")
    _c2, ctrl2 = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "36", date(2026, 10, 1))
    invs = [
        add_invoice(
            app_engine, w, f"cs{i}", f"INV-CS{i}", date(2026, 10, 5 + i), "1", price="50.40", uom="CS"
        )
        for i in range(3)
    ]
    aliases = client.get("/api/v1/aliases", headers=w.headers).json()["items"]
    old = aliases[0]
    ret = client.post(
        f"/api/v1/aliases/{old['id']}/deactivate",
        json={"reason": "units wrong"},
        headers={**w.headers, "If-Match": str(old["version"])},
    )
    assert ret.status_code == 200 and ret.json()["status"] == "retired"
    wrong = client.post(
        "/api/v1/aliases",
        headers=ctrl,
        json={
            "vendor_id": str(w.vendor_id),
            "supplier_item_code": "W-100",
            "item_id": str(w.item_id),
            "conversion_factor": "24",
            "supplier_uom": "CS",
            "item_uom": "EA",
        },
    )
    assert wrong.status_code == 201 and wrong.json()["status"] == "pending_approval"
    match(client, app_engine, w.headers, invs)
    for inv in invs:  # IT-21: before approval every line stops at alias_unconfirmed
        body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
        assert body["lines"][0]["status"] == "exception"
        assert any(e["type"] == "alias_unconfirmed" and e["status"] == "open" for e in body["exceptions"])
    ap = client.get("/api/v1/approvals", params={"subject_type": "alias_conversion"}, headers=ctrl).json()[
        "items"
    ][0]
    own = client.post(
        f"/api/v1/approvals/{ap['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(ap["version"])},
    )
    assert own.status_code == 403  # a second controller exists: no self-approval
    ok = client.post(
        f"/api/v1/approvals/{ap['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl2, "If-Match": str(ap["version"])},
    )
    assert ok.status_code == 200 and ok.json()["match_run_id"]
    drain(app_engine)
    over = [client.get(f"/api/v1/invoices/{i}", headers=w.headers).json() for i in invs]
    assert any(
        e["type"] == "qty_over_received" for b in over for e in b["exceptions"] if e["status"] == "open"
    )
    # IT-15: retire the wrong conversion, create 1 CS = 12 EA, approve; old results superseded, kept.
    wrong_now = next(
        a for a in client.get("/api/v1/aliases", headers=w.headers).json()["items"] if a["status"] == "active"
    )
    client.post(
        f"/api/v1/aliases/{wrong_now['id']}/deactivate",
        json={"reason": "factor is 12"},
        headers={**ctrl, "If-Match": str(wrong_now["version"])},
    )
    right = client.post(
        "/api/v1/aliases",
        headers=w.headers,
        json={
            "vendor_id": str(w.vendor_id),
            "supplier_item_code": "W-100",
            "item_id": str(w.item_id),
            "conversion_factor": "12",
            "supplier_uom": "CS",
            "item_uom": "EA",
        },
    ).json()
    ap2 = next(
        a
        for a in client.get("/api/v1/approvals", headers=ctrl).json()["items"]
        if a["alias_id"] == right["id"]
    )
    assert (
        client.post(
            f"/api/v1/approvals/{ap2['id']}/decision",
            json={"decision": "approve"},
            headers={**ctrl, "If-Match": str(ap2["version"])},
        ).status_code
        == 200
    )
    drain(app_engine)
    for inv in invs:
        assert (
            client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()["lines"][0]["status"] == "matched"
        )
    with session(w.tenant_id, app_engine) as s:
        kept = s.scalars(select(LineMatch).where(LineMatch.is_current.is_(False))).all()
        assert len(kept) >= 6 and all(lm.superseded_by_run_id is not None for lm in kept)


def test_it28_late_receiving_evidence_counts_only_after_approval(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor W4")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "50", date(2026, 10, 1))
    inv = add_invoice(app_engine, w, "inv", "INV-L1", date(2026, 10, 5), "100")
    match(client, app_engine, w.headers, [inv])
    assert queue(client, w.headers, type="qty_over_received", status="open")
    up = client.post(
        "/api/v1/receiving/imports",
        files={"file": ("late.csv", b"PO,Line,Qty,Received\n4471,2,50,2026-10-02\n")},
        data={"evidence_class": "A"},
        headers=w.headers,
    ).json()
    client.put(
        f"/api/v1/receiving/imports/{up['id']}/mapping",
        headers=w.headers,
        json={
            "columns": {
                "po_number": "PO",
                "line_no": "Line",
                "qty_received": "Qty",
                "received_date": "Received",
            }
        },
    )
    c = client.post(f"/api/v1/receiving/imports/{up['id']}/commit", headers=w.headers).json()
    assert c["late_lines"] == 1 and c["late_approval_id"]
    drain(app_engine)
    assert queue(client, w.headers, type="qty_over_received", status="open")  # stays until approved
    ap = client.get("/api/v1/approvals", params={"subject_type": "late_receipt"}, headers=ctrl).json()[
        "items"
    ][0]
    d = client.post(
        f"/api/v1/approvals/{ap['id']}/decision",
        json={"decision": "approve"},
        headers={**ctrl, "If-Match": str(ap["version"])},
    )
    assert d.status_code == 200 and d.json()["effect"] == "late_receipt_approved"
    drain(app_engine)
    assert not queue(client, w.headers, type="qty_over_received", status="open")
    body = client.get(f"/api/v1/invoices/{inv}", headers=w.headers).json()
    assert body["lines"][0]["status"] == "matched"
    detail = client.get(f"/api/v1/receiving/imports/{up['id']}", headers=w.headers).json()
    assert detail["receipts"][0]["lines"][0]["late_approved"] is True


def test_tolerance_versions_preview_and_rematch_and_suggestions(app_engine, client):  # type: ignore[no-untyped-def]
    w = make_tenant(app_engine, "Fictional Distributor W5")
    _c, ctrl = add_user(app_engine, w, "controller")
    add_receipt(app_engine, w, "10", date(2026, 10, 1))
    inv = add_invoice(app_engine, w, "inv", "INV-T1", date(2026, 10, 5), "10", price="4.50")
    match(client, app_engine, w.headers, [inv])
    assert queue(client, w.headers, type="price_variance", status="open")
    pre = client.post("/api/v1/tolerances/preview", json={"price_tol_abs": "0.50"}, headers=ctrl).json()
    assert pre["exceptions_cleared"] == 1
    assert (
        client.put(
            "/api/v1/tolerances/default", json={"price_tol_abs": "0.50"}, headers=w.headers
        ).status_code
        == 403
    )
    first = client.put("/api/v1/tolerances/default", json={"price_tol_abs": "0.50"}, headers=ctrl).json()
    assert first["match_run_id"]
    drain(app_engine)
    second = client.put("/api/v1/tolerances/default", json={"price_tol_abs": "0.40"}, headers=ctrl).json()
    with session(w.tenant_id, app_engine) as s:
        rules = s.scalars(select(ToleranceRule).order_by(ToleranceRule.valid_from)).all()
        assert len(rules) == 2 and rules[0].valid_to is not None and rules[1].valid_to is None
        first_rule = uuid.UUID(first["tolerance"]["id"])
        assert s.scalar(select(LineMatch).where(LineMatch.tolerance_rule_id == first_rule)) is not None
    assert second["tolerance"]["receipt_tolerance"] is None
    drain(app_engine)
    assert not queue(client, w.headers, type="price_variance", status="open")
    tol = client.get("/api/v1/tolerances", headers=w.headers).json()
    assert tol["default"]["price_tol_abs"] == "0.400000" and "no tolerance" in tol["receipt_note"]
    sug = client.get(
        "/api/v1/aliases/suggestions",
        params={"vendor_id": str(w.vendor_id), "code": "W-100", "description": "Synthetic widgets"},
        headers=w.headers,
    ).json()["items"]
    assert sug[0]["basis"] == "earlier_alias" and sug[0]["item_id"] == str(w.item_id)
