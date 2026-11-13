"""T-1.1.1 capture: read the sandbox company through ``IntuitApi`` and keep what came back (B11).

Read only: CompanyInfo, a count and every page of Vendor, Item, PurchaseOrder, Bill and
VendorCredit through the query endpoint (``STARTPOSITION`` / ``MAXRESULTS``). The Accounting API
has no item-receipt entity (AGENTS.md section 3), so none is queried; what the API exposes about
receiving is observed passively: the ``LinkedTxn`` types on purchase orders and bills and the
fields present on purchase-order lines (``summarise``).

Raw answers go to a gitignored folder first. ``sanitise_text`` then removes what identifies the
owner's sandbox before anything may become a fixture: the realm ID (replaced by ``REALM_PLACEHOLDER``
wherever it occurs), Intuit request IDs (``intuit_tid`` header and any ``requestId``-like field), and
e-mail addresses (Intuit sets the sandbox company's e-mail to the developer's sign-in address).
Response headers are cut down to those bearing on call limits. ``leaks`` is the last gate: it names
(never prints) any forbidden value still present, and the script refuses to write if it finds one.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from matchdesk.qbo.intuit_http import ApiAnswer, IntuitApi, limit_headers

CAPTURE_ENTITIES = ("Vendor", "Item", "PurchaseOrder", "Bill", "VendorCredit")
REALM_PLACEHOLDER = "REALM-SANDBOX"
REQUEST_ID_PLACEHOLDER = "REQUEST-ID-REMOVED"
EMAIL_PLACEHOLDER = "removed@example.invalid"
MAX_PAGE_SIZE = 1000  # the largest MAXRESULTS Intuit documents for the query endpoint [assumption]
MAX_PAGES_PER_ENTITY = 200

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
REQUEST_ID_FIELD = re.compile(r'("(?:intuit_tid|requestId|RequestId|request_id|tid)"\s*:\s*")[^"]*(")')
REQUEST_ID_HEADERS = ("intuit_tid", "intuit-tid", "x-request-id", "x-amzn-requestid", "x-amz-cf-id")
DROP_HEADERS = ("set-cookie", "authorization")
# Observed 2026-11-13: ``MetaData.LastModifiedByRef.value`` carries the Intuit user ID of whoever
# owns the sandbox, and ``V4IDPseudonym`` an Intuit pseudonymous ID. Both are replaced.
USER_PLACEHOLDER = "USER-REMOVED"
USER_REF_FIELD = re.compile(r'("(?:LastModifiedByRef|CreatedByRef)"\s*:\s*\{\s*"value"\s*:\s*")[^"]*(")')
PSEUDONYM_FIELD = re.compile(r'("V4IDPseudonym"\s*:\s*")[^"]*(")')


@dataclass
class Capture:
    answers: list[ApiAnswer] = field(default_factory=list)

    def add(self, answer: ApiAnswer) -> ApiAnswer:
        self.answers.append(answer)
        return answer


def capture_all(api: IntuitApi, page_size: int = 100) -> Capture:
    """Every read T-1.1.1 needs, in a fixed order. Stops an entity at its first short or failed page."""
    size = max(1, min(page_size, MAX_PAGE_SIZE))
    cap = Capture()
    cap.add(api.company_info())
    for entity in CAPTURE_ENTITIES:
        cap.add(api.query(f"select count(*) from {entity}"))  # noqa: S608 (fixed entity names, read only)
        start = 1
        for _ in range(MAX_PAGES_PER_ENTITY):
            statement = f"select * from {entity} startposition {start} maxresults {size}"  # noqa: S608
            answer = cap.add(api.query(statement))
            if not answer.ok:
                break
            rows = answer.json().get("QueryResponse", {}).get(entity, [])
            if len(rows) < size:
                break
            start += size
    return cap


def sanitise_text(text: str, realm_id: str) -> str:
    out = text.replace(realm_id, REALM_PLACEHOLDER) if realm_id else text
    out = REQUEST_ID_FIELD.sub(rf"\g<1>{REQUEST_ID_PLACEHOLDER}\g<2>", out)
    out = USER_REF_FIELD.sub(rf"\g<1>{USER_PLACEHOLDER}\g<2>", out)
    out = PSEUDONYM_FIELD.sub(rf"\g<1>{USER_PLACEHOLDER}\g<2>", out)
    return EMAIL.sub(EMAIL_PLACEHOLDER, out)


def user_ids(answers: Iterable[ApiAnswer]) -> set[str]:
    """Intuit user and pseudonym IDs in the raw answers, for the leak gate."""
    found: set[str] = set()
    for a in answers:
        text = a.body.decode("utf-8", "replace")
        for rx in (USER_REF_FIELD, PSEUDONYM_FIELD):
            for m in rx.finditer(text):
                end = text.index('"', m.end(1))
                found.add(text[m.end(1) : end])
    return found


def sanitise_headers(headers: dict[str, str], realm_id: str) -> dict[str, str]:
    kept = limit_headers({k.lower(): v for k, v in headers.items() if k.lower() not in DROP_HEADERS})
    for name in REQUEST_ID_HEADERS:
        if name in {k.lower() for k in headers}:
            kept[name] = REQUEST_ID_PLACEHOLDER
    return {k: sanitise_text(v, realm_id) for k, v in sorted(kept.items())}


def request_ids(answers: Iterable[ApiAnswer]) -> set[str]:
    found: set[str] = set()
    for a in answers:
        for k, v in a.headers.items():
            if k.lower() in REQUEST_ID_HEADERS and v:
                found.add(v)
    return found


def leaks(text: str, forbidden: dict[str, Iterable[str]]) -> list[str]:
    """Names of the forbidden kinds still present in ``text`` (values are never returned)."""
    hits = [
        kind for kind, values in forbidden.items() if any(v and len(v) >= 4 and v in text for v in values)
    ]
    if EMAIL.search(text.replace(EMAIL_PLACEHOLDER, "")):
        hits.append("email address")
    return hits


def sanitised_record(answer: ApiAnswer, realm_id: str) -> str:
    """One answer as JSON text: request (method, path, statement), status, kept headers, and the
    body as Intuit sent it after ``sanitise_text`` (numbers untouched: no float round trip)."""
    body = sanitise_text(answer.body.decode("utf-8", "replace"), realm_id).strip()
    try:
        json.loads(body or "null", parse_float=Decimal, parse_int=Decimal)
    except ValueError:
        body = json.dumps({"unparsed_text": body[:2000]})
    meta = json.dumps(
        {
            "request": {"method": "GET", "path": answer.path, "query": answer.statement},
            "status": answer.status,
            "headers": sanitise_headers(answer.headers, realm_id),
        },
        indent=2,
    )
    return meta[: meta.rindex("}")].rstrip() + ',\n  "body": ' + (body or "null") + "\n}\n"


def summarise(answers: Iterable[ApiAnswer]) -> dict[str, Any]:
    """Shapes for the fact sheet: counts, field names, line detail types, LinkedTxn types, limits."""
    out: dict[str, Any] = {"entities": {}, "statuses": {}, "limit_headers_seen": set()}
    for a in answers:
        out["statuses"][str(a.status)] = out["statuses"].get(str(a.status), 0) + 1
        out["limit_headers_seen"].update(
            k for k in limit_headers(a.headers) if k not in ("date", "content-type")
        )
        if not a.ok:
            continue
        resp = a.json().get("QueryResponse", {})
        for entity in CAPTURE_ENTITIES:
            words = (a.statement or "").split()
            if "count(*)" in words and words[words.index("from") + 1] == entity:
                out["entities"].setdefault(entity, _empty())["count"] = resp.get("totalCount")
            for row in resp.get(entity, []):
                e = out["entities"].setdefault(entity, _empty())
                e["rows"] += 1
                e["fields"].update(row.keys())
                for ln in row.get("Line", []) or []:
                    e["line_fields"].update(ln.keys())
                    if ln.get("DetailType"):
                        e["line_detail_types"].add(str(ln["DetailType"]))
                    for d in ("ItemBasedExpenseLineDetail", "AccountBasedExpenseLineDetail"):
                        if isinstance(ln.get(d), dict):
                            e["line_detail_fields"].update(f"{d}.{k}" for k in ln[d])
                    for t in ln.get("LinkedTxn", []) or []:
                        e["line_linked_txn_types"].add(str(t.get("TxnType")))
                        e["line_linked_txn_fields"].update(t.keys())
                for t in row.get("LinkedTxn", []) or []:
                    e["linked_txn_types"].add(str(t.get("TxnType")))
                if row.get("POStatus") is not None:
                    e["po_status_values"].add(str(row["POStatus"]))
    plain: dict[str, Any] = _plain(out)
    return plain


def _empty() -> dict[str, Any]:
    return {
        "count": None,
        "rows": 0,
        "fields": set(),
        "line_fields": set(),
        "line_detail_types": set(),
        "line_detail_fields": set(),
        "line_linked_txn_types": set(),
        "line_linked_txn_fields": set(),
        "linked_txn_types": set(),
        "po_status_values": set(),
    }


def _plain(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return value if isinstance(value, (str, int, type(None))) else str(value)
