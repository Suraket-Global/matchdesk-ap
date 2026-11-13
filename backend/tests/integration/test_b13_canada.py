"""B13: the Canadian sandbox company as recorded on 2026-11-13 (fixtures/qbo/sandbox-ca, sanitised),
read by a CAD account through the real sync path (request_sync, execute_sync, IntuitQboReader).

What differs from the US company: multicurrency is on (CAD and HKD documents, ``ExchangeRate``),
every purchase order and bill carries ``GlobalTaxCalculation: TaxExcluded`` and ``TxnTaxDetail``
(13 % HST on the CAD documents), line amounts are before tax, and one bill is named by two purchase
orders. The stand-in applies the same filters as Intuit (TxnDate on purchase orders, VendorRef on
bills and credits), so the counts equal the real read on S-04."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from matchdesk.api.app import create_app
from matchdesk.core import load_settings
from matchdesk.qbo import FakeIntuitTokenEndpoint, HttpAnswer, execute_sync, reader_for_tenant, request_sync
from matchdesk.qbo.models import PoLineRow, PurchaseOrderRow, QboBillLineRow, QboBillRow
from matchdesk.tenancy import session

from .seed import auth_headers
from .test_b11_live_qbo import connect, tenant

pytestmark = pytest.mark.integration
SANDBOX_CA = Path(__file__).resolve().parents[2] / "fixtures" / "qbo" / "sandbox-ca"


def body(name: str) -> dict[str, Any]:
    text = next(SANDBOX_CA.glob(f"*-{name}.json")).read_text()
    return json.loads(text)["body"]  # type: ignore[no-any-return]


class FilteringReplay:
    """Intuit stand-in over the recorded Canadian answers, GET only, with Intuit's filters applied."""

    def __init__(self, change: dict[str, dict[str, Any]] | None = None) -> None:
        self.urls: list[str] = []
        self.change = change or {}

    def __call__(self, url: str, headers: dict[str, str], timeout: int) -> HttpAnswer:
        self.urls.append(url)
        if "/companyinfo/" in url:
            return HttpAnswer(200, {}, json.dumps(body("CompanyInfo-page")).encode())
        statement = parse_qs(urlparse(url).query)["query"][0]
        entity = statement.split(" from ")[1].split(" ")[0]
        start = int(re.search(r"startposition (\d+)", statement).group(1))  # type: ignore[union-attr]
        rows = list(body(f"{entity}-page").get("QueryResponse", {}).get(entity, []))
        since = re.search(r"TxnDate >= '([\d-]+)'", statement)
        until = re.search(r"TxnDate <= '([\d-]+)'", statement)
        vendors = re.search(r"VendorRef in \(([^)]*)\)", statement)
        if since:
            rows = [r for r in rows if r["TxnDate"] >= since.group(1)]
        if until:
            rows = [r for r in rows if r["TxnDate"] <= until.group(1)]
        if vendors:
            wanted = set(re.findall(r"'([^']*)'", vendors.group(1)))
            rows = [r for r in rows if r["VendorRef"]["value"] in wanted]
        rows = [{**r, **self.change.get(f"{entity}:{r['Id']}", {})} for r in rows]
        rows = rows if start == 1 else []
        return HttpAnswer(200, {}, json.dumps({"QueryResponse": {entity: rows}}).encode())


def read_canada(app_engine, replay: FilteringReplay):  # type: ignore[no-untyped-def]
    endpoint = FakeIntuitTokenEndpoint()
    client = TestClient(create_app(qbo_token_endpoint=endpoint, qbo_transport=replay))
    tid, uid, token = tenant(app_engine, "intuit", "CAD")
    assert connect(client, endpoint, token, f"realm-{tid}").endswith("result=connected")
    settings = load_settings()
    reader = reader_for_tenant(app_engine, settings, tid, endpoint, replay)
    with session(tid, app_engine) as s:
        run, _ = request_sync(s, tid, uid, "date_range", date(2026, 4, 1), date(2026, 9, 30))
    assert execute_sync(app_engine, tid, run.id, reader, settings.qbo_page_size) == "succeeded"
    last = client.get("/api/v1/qbo/connection", headers=auth_headers(token)).json()["last_sync"]
    return tid, last


def test_canadian_company_is_read_before_tax_and_only_hkd_is_skipped(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_ID", "client-id-invented")
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_SECRET", "client-secret-invented")
    monkeypatch.setenv("MATCHDESK_QBO_REDIRECT_URI", "https://app.matchdesk.test/oauth/intuit/callback")
    replay = FilteringReplay()
    tid, last = read_canada(app_engine, replay)
    assert all(urlparse(u).scheme == "https" for u in replay.urls)
    # The same counts as the real read on S-04 (2026-11-14): nothing in USD, three HKD purchase orders.
    assert last["counts"]["PurchaseOrder"] == 2 and last["counts"]["Bill"] == 1
    assert last["skipped_currency"] == [{"entity": "PurchaseOrder", "currency": "HKD", "count": 3}]
    assert last["home_currency"] == "CAD" and last["skipped_tax_inclusive"] == []
    with session(tid, app_engine) as s:
        pos = {p.po_number: p for p in s.scalars(select(PurchaseOrderRow))}
        assert sorted(pos) == ["1003", "1004"]
        # One bill named by both purchase orders (the link is on the PO header only, as in the US).
        assert pos["1003"].linked_bill_qbo_ids == ["97"] == pos["1004"].linked_bill_qbo_ids
        lines = {
            (p.po_number, pl.line_no): pl
            for p in pos.values()
            for pl in s.scalars(select(PoLineRow).where(PoLineRow.purchase_order_id == p.id))
        }
        # Before tax: 75 x 3.50 = 262.50 although the PO total is 296.63 with 13 % HST.
        assert lines[("1003", 1)].unit_price == Decimal("3.5") and lines[("1003", 1)].amount == Decimal(
            "262.50"
        )
        bill = s.scalar(select(QboBillRow).where(QboBillRow.qbo_id == "97"))
        assert bill is not None and bill.total == Decimal("508.51")  # TotalAmt includes the tax
        bill_lines = s.scalars(select(QboBillLineRow).where(QboBillLineRow.qbo_bill_id == bill.id)).all()
        assert sum((bl.amount or Decimal(0)) for bl in bill_lines) == Decimal("450.00")  # 508.51 - 58.51
        attributed = {
            next(k for k, v in lines.items() if v.id == bl.po_line_id) for bl in bill_lines if bl.po_line_id
        }
        assert attributed == {("1003", 1), ("1004", 1)}  # by item, across the two purchase orders
        assert s.scalar(select(func.count()).select_from(QboBillRow).where(QboBillRow.qbo_id == "98")) == 0


def test_a_tax_inclusive_document_is_not_stored_and_is_named(app_engine, monkeypatch):  # type: ignore[no-untyped-def]
    """Not observed: if QuickBooks sent amounts that include tax, MatchDesk would compare a taxed price
    with an untaxed one. Such a purchase order is left out and S-04 says so."""
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_ID", "client-id-invented")
    monkeypatch.setenv("MATCHDESK_QBO_CLIENT_SECRET", "client-secret-invented")
    monkeypatch.setenv("MATCHDESK_QBO_REDIRECT_URI", "https://app.matchdesk.test/oauth/intuit/callback")
    replay = FilteringReplay({"PurchaseOrder:96": {"GlobalTaxCalculation": "TaxInclusive"}})
    tid, last = read_canada(app_engine, replay)
    assert last["skipped_tax_inclusive"] == [{"entity": "PurchaseOrder", "count": 1}]
    assert last["counts"]["PurchaseOrder"] == 1
    with session(tid, app_engine) as s:
        assert [p.po_number for p in s.scalars(select(PurchaseOrderRow))] == ["1003"]


def test_recorded_canadian_shapes() -> None:
    """Contract over the committed fixtures: what the Canadian company sends."""
    pos = body("PurchaseOrder-page")["QueryResponse"]["PurchaseOrder"]
    bills = body("Bill-page")["QueryResponse"]["Bill"]
    assert {r["CurrencyRef"]["value"] for r in pos + bills} == {"CAD", "HKD"}
    for r in pos + bills:
        assert r["GlobalTaxCalculation"] == "TaxExcluded"
        lines = sum(Decimal(str(ln["Amount"])) for ln in r["Line"])
        tax = Decimal(str(r["TxnTaxDetail"]["TotalTax"]))
        assert lines + tax == Decimal(str(r["TotalAmt"]))  # amounts before tax; tax only in the total
        for ln in r["Line"]:
            detail = ln.get("ItemBasedExpenseLineDetail")
            if detail:
                assert Decimal(str(detail["Qty"])) * Decimal(str(detail["UnitPrice"])) == pytest.approx(
                    Decimal(str(ln["Amount"])), abs=Decimal("0.01")
                )
                assert "TaxCodeRef" in detail  # an id ("5", "2"), not "NON" as in the US company
    cad = [r for r in pos + bills if r["CurrencyRef"]["value"] == "CAD"]
    assert {line["TaxLineDetail"]["TaxPercent"] for r in cad for line in r["TxnTaxDetail"]["TaxLine"]} == {13}
    assert all(r.get("ExchangeRate") is not None for r in pos + bills)
    assert all(ln.get("LinkedTxn", []) == [] for b in bills for ln in b["Line"])
    assert body("VendorCredit-page").get("QueryResponse", {}).get("VendorCredit", []) == []
