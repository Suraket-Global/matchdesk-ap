"""QuickBooks Online behind an interface (read only; no write method exists).

T-1.1.1 (sandbox fact sheet) is blocked in B1: no developer account, no keys,
no real calls. ``FakeQboReader`` serves recorded synthetic records so sync and
matching can be built and tested; the real ``httpx`` client is written after
the fact sheet confirms what the API returns for linked bill lines and credits.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


class QboReader(Protocol):
    """The five entity types MatchDesk reads (MH-02). There is deliberately no write method."""

    def vendors(self) -> Iterable[dict[str, Any]]: ...
    def items(self) -> Iterable[dict[str, Any]]: ...
    def purchase_orders(self, references: list[str] | None = None) -> Iterable[dict[str, Any]]: ...
    def bills(self, vendor_ids: list[str]) -> Iterable[dict[str, Any]]: ...
    def vendor_credits(self, vendor_ids: list[str]) -> Iterable[dict[str, Any]]: ...


@dataclass
class FakeQboReader:
    """In-memory reader over synthetic records shaped as an assumption of the real API."""

    vendor_rows: list[dict[str, Any]] = field(default_factory=list)
    item_rows: list[dict[str, Any]] = field(default_factory=list)
    po_rows: list[dict[str, Any]] = field(default_factory=list)
    bill_rows: list[dict[str, Any]] = field(default_factory=list)
    credit_rows: list[dict[str, Any]] = field(default_factory=list)

    def vendors(self) -> Iterable[dict[str, Any]]:
        return list(self.vendor_rows)

    def items(self) -> Iterable[dict[str, Any]]:
        return list(self.item_rows)

    def purchase_orders(self, references: list[str] | None = None) -> Iterable[dict[str, Any]]:
        if references is None:
            return list(self.po_rows)
        return [p for p in self.po_rows if p["DocNumber"] in references]

    def bills(self, vendor_ids: list[str]) -> Iterable[dict[str, Any]]:
        return [b for b in self.bill_rows if b["VendorRef"] in vendor_ids]

    def vendor_credits(self, vendor_ids: list[str]) -> Iterable[dict[str, Any]]:
        return [c for c in self.credit_rows if c["VendorRef"] in vendor_ids]
