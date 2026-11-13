"""QuickBooks Online behind an interface (read only; no write method exists).

T-1.1.1 (sandbox fact sheet) is blocked: no Intuit developer account, no keys, no real
calls. Two readers exist:

- ``FakeQboReader``: in-memory rows for unit tests.
- ``RecordedQboReader``: synthetic JSON files shaped as the Accounting API is assumed to
  answer a query (``{"QueryResponse": {"PurchaseOrder": [...]}}``, entity fields as in
  Intuit's public reference). **Shape unverified until T-1.1.1.** Paging imitates the
  API's ``STARTPOSITION`` / ``MAXRESULTS`` (1-based start).

``IntuitQboReader`` is the real client's place: selected per tenant (``tenants.qbo_mode``, else
``MATCHDESK_QBO_MODE``). Since B11 it holds the GET-only ``IntuitApi`` of the tenant's connection,
but ``page()`` still refuses: the mapping is written from the responses T-1.1.1 records, not from
assumptions (B11 phase B).

There is no item-receipt entity in the Accounting API (SRC-16); no reader returns receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from matchdesk.core import Settings

if TYPE_CHECKING:
    from matchdesk.qbo.intuit_http import IntuitApi

ENTITIES = ("Vendor", "Item", "PurchaseOrder", "Bill", "VendorCredit")


class QboNotConfiguredError(RuntimeError):
    """The real Intuit client is selected but not configured (no developer account, T-1.1.1)."""


class QboTransientError(RuntimeError):
    """HTTP 429, 5xx or a network error: the sync retries and resumes from its cursor."""


@dataclass(frozen=True)
class PageQuery:
    """What one sync asks for. ``references``: PO numbers (mode ``po_references``); ``since`` and
    ``until``: PO transaction dates (mode ``date_range``); ``vendor_ids``: bills and credits of these
    vendors, with no date filter (history, AD-13)."""

    references: tuple[str, ...] | None = None
    since: date | None = None
    until: date | None = None
    vendor_ids: tuple[str, ...] | None = None


class QboReader(Protocol):
    """The five entity types MatchDesk reads (MH-02). There is deliberately no write method."""

    def page(self, entity: str, start: int, size: int, query: PageQuery) -> list[dict[str, Any]]: ...


def _ref(row: dict[str, Any], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, dict):
        return str(value.get("value")) if value.get("value") is not None else None
    return str(value) if value is not None else None


def _matches(entity: str, row: dict[str, Any], q: PageQuery) -> bool:
    if entity == "PurchaseOrder":
        if q.references is not None:
            return str(row.get("DocNumber")) in q.references
        txn = date.fromisoformat(str(row["TxnDate"]))
        return (q.since is None or txn >= q.since) and (q.until is None or txn <= q.until)
    if entity in ("Bill", "VendorCredit"):
        return q.vendor_ids is None or _ref(row, "VendorRef") in q.vendor_ids
    return True


def _page(
    rows: list[dict[str, Any]], entity: str, start: int, size: int, q: PageQuery
) -> list[dict[str, Any]]:
    selected = sorted((r for r in rows if _matches(entity, r, q)), key=lambda r: str(r.get("Id")))
    return selected[start - 1 : start - 1 + size]


@dataclass
class FakeQboReader:
    """In-memory reader over synthetic rows shaped as an assumption of the real API."""

    rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[tuple[str, int]] = field(default_factory=list)
    fail_on: set[tuple[str, int]] = field(default_factory=set)

    def page(self, entity: str, start: int, size: int, query: PageQuery) -> list[dict[str, Any]]:
        self.calls.append((entity, start))
        if (entity, start) in self.fail_on:
            self.fail_on.discard((entity, start))
            raise QboTransientError("simulated interruption")
        return _page(self.rows.get(entity, []), entity, start, size, query)


class RecordedQboReader(FakeQboReader):
    """Reads ``<dir>/<Entity>.json`` files in the assumed query-response shape (shape unverified
    until T-1.1.1). Numbers are parsed as ``Decimal``, never as binary floats."""

    def __init__(self, directory: Path | str) -> None:
        rows: dict[str, list[dict[str, Any]]] = {}
        for entity in ENTITIES:
            path = Path(directory) / f"{entity}.json"
            if path.exists():
                body = json.loads(path.read_text(), parse_float=Decimal, parse_int=Decimal)
                rows[entity] = list(body.get("QueryResponse", {}).get(entity, []))
        super().__init__(rows=rows)


class IntuitQboReader:
    """The live reader over ``IntuitApi`` (GET only). ``page()`` is written after T-1.1.1 records the
    real responses; until then it refuses, so nothing is mapped from an assumed shape."""

    def __init__(self, settings: Settings, api: IntuitApi | None = None) -> None:
        self.settings = settings
        self.api = api

    def page(self, entity: str, start: int, size: int, query: PageQuery) -> list[dict[str, Any]]:
        raise QboNotConfiguredError("live QuickBooks reader not built yet: T-1.1.1 runs first (B11 phase B)")


DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "qbo" / "recorded"


def reader_from_settings(settings: Settings) -> QboReader:
    if settings.qbo_mode == "recorded":
        return RecordedQboReader(settings.qbo_fixtures_dir or DEFAULT_FIXTURES)
    if settings.qbo_mode == "intuit":
        return IntuitQboReader(settings)
    raise QboNotConfiguredError(f"unknown QuickBooks mode {settings.qbo_mode}")
