"""QuickBooks Online item receipts as receiving evidence (Decision.md section 3, C1 2026-11-11).

QuickBooks Online can record an item receipt against a purchase order before the
supplier's bill arrives (Intuit Canada help article, SRC-15). The QuickBooks Online
Accounting API has no ItemReceipt entity (SRC-16), so item receipts reach MatchDesk
only as a report or CSV export the account uploads: ``receiving_imports.source_type``
``qbo_item_receipt_export``, always evidence class A.

An item receipt is independent receiving evidence only when the person who saw the
goods recorded it before the bill, and that person is not someone who enters bills
or clears exceptions. Each exported row is tested here; a row that fails is listed
with its reason in the import's rejected rows and never becomes a receipt line.
Which export carries the creator and creation time is unverified until T-1.1.1;
a row without them is rejected, never assumed independent.

Pure: no database, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

SOURCE_TYPE = "qbo_item_receipt_export"


class ItemReceiptRejection(StrEnum):
    CREATOR_UNKNOWN = "creator_unknown"
    CREATED_AT_UNKNOWN = "created_at_unknown"
    ENTERED_BY_AP_STAFF = "entered_by_ap_staff"
    ENTERED_BY_BILL_ENTERER = "entered_by_bill_enterer"
    ENTERED_AFTER_BILL = "entered_after_bill"


@dataclass(frozen=True)
class QboItemReceiptRow:
    """One exported item-receipt line, with the audit fields of the export."""

    po_number: str
    created_by: str | None
    created_at: datetime | None
    linked_bill_created_by: str | None = None
    linked_bill_created_at: datetime | None = None


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def item_receipt_rejection(row: QboItemReceiptRow, ap_staff: frozenset[str]) -> ItemReceiptRejection | None:
    """``None`` when the row counts as class A; otherwise the reason it does not.

    ``ap_staff`` are the QuickBooks user names the controller attests enter bills or
    resolve exceptions (the pilot's evidence-class attestation).
    """
    if row.created_by is None or not row.created_by.strip():
        return ItemReceiptRejection.CREATOR_UNKNOWN
    if row.created_at is None:
        return ItemReceiptRejection.CREATED_AT_UNKNOWN
    creator = _norm(row.created_by)
    if creator in {_norm(s) for s in ap_staff}:
        return ItemReceiptRejection.ENTERED_BY_AP_STAFF
    if row.linked_bill_created_by is not None and _norm(row.linked_bill_created_by) == creator:
        return ItemReceiptRejection.ENTERED_BY_BILL_ENTERER
    if row.linked_bill_created_at is not None and row.created_at >= row.linked_bill_created_at:
        return ItemReceiptRejection.ENTERED_AFTER_BILL
    return None
