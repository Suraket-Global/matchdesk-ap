"""B11 unit tests: the GET-only Intuit client, Intuit token-endpoint errors, the T-1.1.1 capture and
its sanitising. No network: every HTTP answer here is invented."""

from __future__ import annotations

import dataclasses
import io
import json
import urllib.error
import urllib.parse
from email.message import Message
from typing import Any

import pytest

from matchdesk.core import load_settings
from matchdesk.qbo import (
    HttpAnswer,
    IntuitApi,
    IntuitTokenEndpoint,
    QboAuthError,
    QboNotConfiguredError,
    QboTransientError,
    RefreshExpiredError,
)
from matchdesk.qbo.capture import (
    EMAIL_PLACEHOLDER,
    REALM_PLACEHOLDER,
    REQUEST_ID_PLACEHOLDER,
    capture_all,
    leaks,
    request_ids,
    sanitise_headers,
    sanitise_text,
    sanitised_record,
    summarise,
)

REALM = "9341450000000001"  # invented


def settings():  # type: ignore[no-untyped-def]
    return dataclasses.replace(
        load_settings(),
        qbo_client_id="client-id-invented",
        qbo_client_secret="client-secret-invented",
        qbo_redirect_uri="http://localhost:5173/oauth/intuit/callback",
    )


class Transport:
    """Answers GETs from a queue; records each URL and header set (there is no other method)."""

    def __init__(self, answers: list[HttpAnswer]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: int) -> HttpAnswer:
        self.calls.append((url, headers))
        return self.answers.pop(0)


class Tokens:
    def __init__(self) -> None:
        self.n = 0
        self.rejected: list[str | None] = []

    def __call__(self, rejected: str | None) -> str:
        self.rejected.append(rejected)
        if rejected is not None or self.n == 0:
            self.n += 1
        return f"token-{self.n}"


def ok(body: dict[str, Any], **headers: str) -> HttpAnswer:
    return HttpAnswer(200, {"content-type": "application/json", **headers}, json.dumps(body).encode())


def test_query_url_minor_version_and_bearer_token() -> None:
    t = Transport([ok({"QueryResponse": {}}), ok({"CompanyInfo": {}})])
    api = IntuitApi(settings(), REALM, Tokens(), transport=t)
    answer = api.query("select * from PurchaseOrder startposition 1 maxresults 10")
    url, headers = t.calls[0]
    parts = urllib.parse.urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}" == "https://sandbox-quickbooks.api.intuit.com"
    assert parts.path == f"/v3/company/{REALM}/query"
    q = urllib.parse.parse_qs(parts.query)
    assert q["query"] == ["select * from PurchaseOrder startposition 1 maxresults 10"]
    assert q["minorversion"] == [settings().qbo_minor_version]
    assert headers == {"Authorization": "Bearer token-1", "Accept": "application/json"}
    # What is kept of a read names the realm by placeholder and never holds the token.
    assert answer.path == "/v3/company/{realmId}/query" and "token" not in repr(answer)
    api.company_info()
    assert urllib.parse.urlsplit(t.calls[1][0]).path == f"/v3/company/{REALM}/companyinfo/{REALM}"


def test_only_select_statements_are_sent() -> None:
    t = Transport([])
    api = IntuitApi(settings(), REALM, Tokens(), transport=t)
    for bad in ("delete from Bill", "update Vendor set x=1", " insert into Item"):
        with pytest.raises(ValueError):
            api.query(bad)
    assert t.calls == []
    public = {n for n in dir(IntuitApi) if not n.startswith("_")}
    assert public == {"query", "company_info"}


def test_401_refreshes_once_naming_the_refused_token_then_retries() -> None:
    tokens = Tokens()
    t = Transport([HttpAnswer(401, {}, b""), ok({"QueryResponse": {}})])
    IntuitApi(settings(), REALM, tokens, transport=t).query("select * from Vendor")
    assert tokens.rejected == [None, "token-1"]
    assert [h["Authorization"] for _u, h in t.calls] == ["Bearer token-1", "Bearer token-2"]
    t2 = Transport([HttpAnswer(401, {}, b""), HttpAnswer(401, {}, b"")])
    with pytest.raises(QboAuthError):
        IntuitApi(settings(), REALM, Tokens(), transport=t2).query("select * from Vendor")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_limits_and_server_errors_are_transient(status: int) -> None:
    t = Transport([HttpAnswer(status, {"retry-after": "60"}, b"")])
    with pytest.raises(QboTransientError):
        IntuitApi(settings(), REALM, Tokens(), transport=t).query("select * from Item")


def test_a_400_is_returned_for_the_record() -> None:
    t = Transport([HttpAnswer(400, {}, b'{"Fault":{"type":"ValidationFault"}}')])
    answer = IntuitApi(settings(), REALM, Tokens(), transport=t).query("select * from Nothing")
    assert answer.status == 400 and not answer.ok


# --- Intuit token endpoint (only POSTs in the product: exchange, refresh, revoke) ---


class Opener:
    def __init__(self, status: int = 200, body: dict[str, Any] | None = None, exc: Exception | None = None):
        self.status, self.body, self.exc = status, body or {}, exc
        self.requests: list[Any] = []

    def __call__(self, req: Any, timeout: float) -> Any:
        self.requests.append(req)
        if self.exc is not None:
            raise self.exc
        data = json.dumps(self.body).encode()
        if self.status >= 400:
            raise urllib.error.HTTPError(req.full_url, self.status, "x", Message(), io.BytesIO(data))
        return _Resp(data)


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *a: object) -> None:
        return None


def test_token_endpoint_posts_the_form_to_the_settings_url() -> None:
    opener = Opener(body={"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    ep = IntuitTokenEndpoint(settings(), opener=opener)
    assert ep.refresh("r0")["access_token"] == "a"
    req = opener.requests[0]
    assert req.get_method() == "POST" and req.full_url == settings().qbo_token_url
    assert urllib.parse.parse_qs(req.data.decode()) == {
        "grant_type": ["refresh_token"],
        "refresh_token": ["r0"],
    }
    assert req.get_header("Authorization").startswith("Basic ")


def test_token_endpoint_errors_map_without_carrying_the_body() -> None:
    secret_body = {"error": "invalid_grant", "error_description": "token-r0-is-dead"}
    with pytest.raises(RefreshExpiredError) as refused:
        IntuitTokenEndpoint(settings(), opener=Opener(400, secret_body)).refresh("r0")
    assert "token-r0" not in str(refused.value)
    with pytest.raises(PermissionError):
        IntuitTokenEndpoint(settings(), opener=Opener(400, {"error": "invalid_grant"})).exchange("c", "u")
    with pytest.raises(QboNotConfiguredError):
        IntuitTokenEndpoint(settings(), opener=Opener(401, {"error": "invalid_client"})).refresh("r0")
    with pytest.raises(QboTransientError):
        IntuitTokenEndpoint(settings(), opener=Opener(503)).refresh("r0")
    with pytest.raises(QboTransientError):
        IntuitTokenEndpoint(settings(), opener=Opener(exc=urllib.error.URLError("down"))).refresh("r0")


def test_tests_never_see_the_app_credentials() -> None:
    s = load_settings()
    assert s.qbo_client_id == "" and s.qbo_client_secret == "" and s.qbo_redirect_uri == ""


# --- T-1.1.1 capture and sanitising ---


def test_capture_pages_every_entity_with_get_only() -> None:
    answers = [ok({"CompanyInfo": {"CompanyName": "Sandbox Company (invented)"}})]
    for entity in ("Vendor", "Item", "PurchaseOrder", "Bill", "VendorCredit"):
        answers.append(ok({"QueryResponse": {"totalCount": 3}}))
        answers.append(ok({"QueryResponse": {entity: [{"Id": "1"}, {"Id": "2"}]}}))
        answers.append(ok({"QueryResponse": {entity: [{"Id": "3"}]}}))
    t = Transport(answers)
    cap = capture_all(IntuitApi(settings(), REALM, Tokens(), transport=t), page_size=2)
    assert len(cap.answers) == 16 and t.answers == []
    statements = [a.statement for a in cap.answers]
    assert "select * from PurchaseOrder startposition 3 maxresults 2" in statements
    assert all(s is None or s.startswith("select ") for s in statements)
    summary = summarise(cap.answers)
    assert summary["entities"]["Bill"]["rows"] == 3 and summary["entities"]["Bill"]["count"] == 3


def test_sanitise_removes_realm_request_ids_and_emails() -> None:
    body = json.dumps(
        {
            "CompanyInfo": {"Id": "1", "Email": {"Address": "owner.person@gmail.com"}, "Realm": REALM},
            "requestId": "1-abc-req",
            "TotalAmt": 1234.50,
        }
    ).encode()
    from matchdesk.qbo import ApiAnswer

    a = ApiAnswer(
        "/v3/company/{realmId}/companyinfo/{realmId}",
        None,
        200,
        {"intuit_tid": "1-tid-xyz", "set-cookie": "s=1", "content-type": "application/json", "server": "x"},
        body,
    )
    text = sanitised_record(a, REALM)
    assert (
        REALM not in text
        and "owner.person" not in text
        and "1-abc-req" not in text
        and "1-tid-xyz" not in text
    )
    assert REALM_PLACEHOLDER in text and EMAIL_PLACEHOLDER in text and REQUEST_ID_PLACEHOLDER in text
    assert "set-cookie" not in text and '"server"' not in text
    assert "1234.5" in text  # numbers pass through as text, no float round trip
    forbidden = {"realm ID": [REALM], "request ID": sorted(request_ids([a]))}
    assert leaks(text, forbidden) == []
    assert leaks(body.decode(), forbidden) == ["realm ID", "email address"]


def test_limit_headers_are_kept_and_others_dropped() -> None:
    kept = sanitise_headers(
        {"X-RateLimit-Remaining": "499", "Retry-After": "60", "intuit_tid": "t", "Server": "nginx"}, REALM
    )
    assert kept == {"intuit_tid": REQUEST_ID_PLACEHOLDER, "retry-after": "60", "x-ratelimit-remaining": "499"}
    assert sanitise_text("a@b.example", REALM) == EMAIL_PLACEHOLDER


# --- Phase B: the live reader against the responses recorded from the sandbox on 2026-11-13 ---

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

from matchdesk.matching import evaluate, input_fingerprint  # noqa: E402
from matchdesk.qbo import IntuitQboReader, PageQuery, QboReadError, build_statement  # noqa: E402

from .builders import build, class_a, invoice, po_4471, qbo_bill, receipt, replace  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2] / "fixtures" / "qbo" / "sandbox"


def recorded(entity: str) -> bytes:
    """The body Intuit returned for the first page of ``entity`` (sanitised, committed fixture)."""
    page = next(SANDBOX.glob(f"*-{entity}-page.json"))
    text = page.read_text()
    return text[text.index('"body": ') + len('"body": ') : text.rstrip().rindex("}")].strip().encode()


class Replay:
    """Answers each query with the recorded page of the entity it names."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: int) -> HttpAnswer:
        statement = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["query"][0]
        self.statements.append(statement)
        entity = statement.split(" from ")[1].split(" ")[0]
        return HttpAnswer(200, {"content-type": "application/json"}, recorded(entity))


def reader() -> tuple[IntuitQboReader, Replay]:
    t = Replay()
    return IntuitQboReader(settings(), IntuitApi(settings(), REALM, Tokens(), transport=t)), t


def test_contract_recorded_purchase_orders_bills_and_empty_credits() -> None:
    r, _t = reader()
    pos = r.page("PurchaseOrder", 1, 100, PageQuery(since=date(2026, 10, 1), until=date(2026, 10, 31)))
    assert sorted(p["DocNumber"] for p in pos) == ["1002", "1003", "1004"]
    po = next(p for p in pos if p["DocNumber"] == "1004")
    assert po["LinkedTxn"] == [{"TxnId": "126", "TxnType": "Bill"}]  # the link is on the PO only
    line = po["Line"][0]["ItemBasedExpenseLineDetail"]
    assert isinstance(line["Qty"], Decimal) and line["UnitPrice"] == Decimal("10")
    assert "ReceivedQty" not in line and all("LinkedTxn" not in ln for ln in po["Line"])
    bills = r.page("Bill", 1, 100, PageQuery(vendor_ids=("46",)))
    b126 = next(b for b in bills if b["Id"] == "126")
    assert b126["LinkedTxn"] == [] and all(ln["LinkedTxn"] == [] for ln in b126["Line"])
    assert "DocNumber" not in b126  # the sample bills carry no number
    assert r.page("VendorCredit", 1, 100, PageQuery(vendor_ids=("46",))) == []  # {"QueryResponse": {}}
    assert {v["CurrencyRef"]["value"] for v in pos} == {"USD"}


def test_statements_are_filtered_ordered_and_quoted() -> None:
    q = build_statement("PurchaseOrder", 101, 100, PageQuery(references=("4471", "O'Neil\\1")))
    assert q == (
        "select * from PurchaseOrder where DocNumber in ('4471', 'O\\'Neil\\\\1') "
        "orderby Id startposition 101 maxresults 100"
    )
    assert build_statement(
        "PurchaseOrder", 1, 10, PageQuery(since=date(2026, 10, 1), until=date(2026, 10, 31))
    ) == (
        "select * from PurchaseOrder where TxnDate >= '2026-10-01' and TxnDate <= '2026-10-31' "
        "orderby Id startposition 1 maxresults 10"
    )
    assert build_statement("Bill", 1, 10, PageQuery(vendor_ids=("46", "41"))).startswith(
        "select * from Bill where VendorRef in ('46', '41') orderby Id"
    )
    assert "where Active in (true, false)" in build_statement("Vendor", 1, 10, PageQuery())


def test_no_vendor_in_scope_asks_nothing_and_a_refusal_raises() -> None:
    r, t = reader()
    assert r.page("Bill", 1, 10, PageQuery(vendor_ids=())) == [] and t.statements == []
    bad = IntuitQboReader(
        settings(),
        IntuitApi(settings(), REALM, Tokens(), transport=Transport([HttpAnswer(400, {}, b'{"Fault":{}}')])),
    )
    with pytest.raises(QboReadError):
        bad.page("Item", 1, 10, PageQuery())
    with pytest.raises(QboNotConfiguredError):
        IntuitQboReader(settings()).page("Item", 1, 10, PageQuery())


def test_unattributed_quickbooks_bill_on_a_po_blocks_a_pass() -> None:
    base = {
        "po": po_4471(),
        "imports": (class_a(),),
        "receipts": (receipt("r1", "100", date(2026, 10, 1)),),
    }
    oct_inv = invoice("oct", "INV-2", date(2026, 10, 5), "40")
    assert evaluate(build(docs=(oct_inv,), **base)).line("oct-l1").status.value == "matched"
    loose = replace(
        qbo_bill("qb1", "", date(2026, 9, 20), "60", "252.00", po_line=None), unattributed_po_ids=("po-4471",)
    )
    res = evaluate(build(docs=(oct_inv,), bills=(loose,), **base))
    assert res.line("oct-l1").status.value == "exception"
    assert "history_incomplete" in {e.type.value for e in res.exceptions}
    # A bill dated after the invoice does not reach back; an uploaded copy of it is counted instead.
    later = replace(loose, txn_date=date(2026, 10, 20))
    assert evaluate(build(docs=(oct_inv,), bills=(later,), **base)).line("oct-l1").status.value == "matched"


def test_fingerprint_unchanged_while_no_bill_is_unattributed() -> None:
    bill = qbo_bill("qb1", "INV-1", date(2026, 9, 20), "60", "252.00")
    inp = build(docs=(invoice("oct", "INV-2", date(2026, 10, 5), "40"),), bills=(bill,))
    from matchdesk.matching.fingerprint import _canonical

    assert "unattributed_po_ids" not in _canonical(bill)  # so results stored before B11 stay current
    assert input_fingerprint(inp) == input_fingerprint(replace(inp))
    moved = replace(inp, qbo_bills=(replace(bill, unattributed_po_ids=("po-4471",)),))
    assert input_fingerprint(moved) != input_fingerprint(inp)
