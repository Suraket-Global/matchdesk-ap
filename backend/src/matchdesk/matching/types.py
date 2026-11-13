"""Plain input and output data for the rule engine (TRD section 8.5, T-4.1.2 (a)).

Everything here is immutable and uses ``Decimal``. The engine takes these
values as arguments and returns decisions; it never reads a database, a
network or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class EvidenceClass(StrEnum):
    A = "A"  # warehouse record
    B = "B"  # receiver-attested delivery document
    C = "C"  # supplier document only: never counts


class LineKind(StrEnum):
    ITEM = "item"
    FREIGHT = "freight"
    FEE = "fee"
    DISCOUNT = "discount"


class DocType(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    HUMAN_CONFIRMED = "human_confirmed"
    HUMAN_CONFIRMED_INCONSISTENT = "human_confirmed_inconsistent"


class AliasStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"
    RETURNED = "returned"


class LineStatus(StrEnum):
    MATCHED = "matched"
    CHARGE_OK = "charge_ok"
    EXCEPTION = "exception"
    NOT_EVALUATED = "not_evaluated"


class ExceptionType(StrEnum):
    EXTRACTION_UNVERIFIED = "extraction_unverified"
    DUPLICATE = "duplicate"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    NO_PO = "no_po"
    ALIAS_UNCONFIRMED = "alias_unconfirmed"
    PO_LINE_NOT_FOUND = "po_line_not_found"
    UOM_UNRESOLVED = "uom_unresolved"
    HISTORY_INCOMPLETE = "history_incomplete"
    RECEIPT_ABSENT = "receipt_absent"
    QTY_OVER_RECEIVED = "qty_over_received"
    QTY_OVER_ORDERED = "qty_over_ordered"
    PRICE_VARIANCE = "price_variance"
    UNMATCHED_CHARGE = "unmatched_charge"
    CREDIT_UNLINKED = "credit_unlinked"
    CURRENCY_UNSUPPORTED = "currency_unsupported"


class SubReason(StrEnum):
    NOT_RECEIVED = "not_received"
    SUPPLIER_SLIP_ONLY = "supplier_slip_only"
    NO_EVIDENCE = "no_evidence"
    RETURNED_NO_CREDIT = "returned_no_credit"


class ValueClass(StrEnum):
    FINDING_CANDIDATE = "finding_candidate"
    OPEN_UNDECIDED = "open_undecided"
    UNVERIFIED = "unverified"
    NONE = "none"


class ExceptionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ResolutionCode(StrEnum):
    RESOLVED_BY_CREDIT = "resolved_by_credit"
    CONFIRMED_NOT_RECEIVED = "confirmed_not_received"


class DuplicateDecision(StrEnum):
    CONFIRMED_DUPLICATE = "confirmed_duplicate"
    NOT_A_DUPLICATE = "not_a_duplicate"


class CreditDecision(StrEnum):
    """The controller's decision on a "possibly credited in QuickBooks" flag (MH-09; B9)."""

    CREDITED = "credited"
    NOT_CREDITED = "not_credited"


@dataclass(frozen=True)
class CreditDecisionInput:
    """One decision: the exception (document, line or "", type), the vendor credit, the decision."""

    document_id: str
    line_id: str
    type: str
    qbo_bill_id: str
    decision: CreditDecision

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.document_id, self.line_id, self.type)


@dataclass(frozen=True)
class Tolerance:
    """One tolerance rule. ``price_tol_pct`` is in percent: 0.5 means 0.5 %.

    There is no receipt tolerance, by design (MH-07).
    """

    qty_tolerance: Decimal = Decimal("0")
    price_tol_abs: Decimal = Decimal("0.01")
    price_tol_pct: Decimal = Decimal("0.5")
    charge_allowance: Decimal = Decimal("0")
    rule_id: str | None = None


@dataclass(frozen=True)
class PoLine:
    id: str
    line_no: int
    item_id: str | None
    qty_ordered: Decimal
    uom: str | None
    unit_price: Decimal
    qbo_billed_qty: Decimal | None = None  # invoiced side only; never a receipt (AD-05)
    charge_kind: LineKind | None = None  # set when the PO line is a charge (freight, fee)
    amount: Decimal | None = None


@dataclass(frozen=True)
class PurchaseOrder:
    id: str
    vendor_id: str
    po_number: str
    txn_date: date
    lines: tuple[PoLine, ...]


@dataclass(frozen=True)
class Alias:
    id: str
    vendor_id: str
    supplier_item_code: str
    item_id: str
    status: AliasStatus
    conversion_factor: Decimal = Decimal("1")  # item units per supplier unit
    supplier_uom: str | None = None
    item_uom: str | None = None
    approved: bool = False


@dataclass(frozen=True)
class ReceivingImport:
    id: str
    evidence_class: EvidenceClass
    committed: bool
    voided: bool = False
    declared_complete: bool = False
    coverage_start: date | None = None
    coverage_end: date | None = None


@dataclass(frozen=True)
class ReceiptLine:
    id: str
    import_id: str
    po_line_id: str
    qty_in_po_uom: Decimal  # negative for a return to the supplier
    received_date: date
    receiver_marks_recorded: bool = False  # class B: marks and signer recorded
    added_after_exception: bool = False
    late_approved: bool = False


@dataclass(frozen=True)
class DocLine:
    id: str
    line_no: int
    kind: LineKind = LineKind.ITEM
    supplier_item_code: str | None = None
    qty: Decimal | None = None
    uom: str | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass(frozen=True)
class Document:
    """An uploaded invoice or credit note after extraction."""

    id: str
    doc_type: DocType
    vendor_id: str
    doc_number: str | None
    doc_date: date | None
    file_sha256: bytes
    verification: VerificationStatus
    lines: tuple[DocLine, ...]
    po_number: str | None = None
    currency: str | None = None
    total: Decimal | None = None
    references_invoice_number: str | None = None  # credit notes


@dataclass(frozen=True)
class QboBillLine:
    id: str
    po_line_id: str | None
    qty: Decimal | None
    amount: Decimal


@dataclass(frozen=True)
class QboBill:
    """A QuickBooks bill or vendor credit, local copy (read only)."""

    id: str
    txn_type: str  # "bill" or "vendor_credit"
    vendor_id: str
    doc_number: str | None
    txn_date: date | None
    total: Decimal
    lines: tuple[QboBillLine, ...] = ()
    references_invoice_number: str | None = None  # vendor credits tied by invoice number
    # B11 (T-1.1.1): POs that name this bill in their own LinkedTxn while an item line of the bill
    # fits no single line of them. Its quantity is unknown history on those POs (TRD 8.5). Left out
    # of the input fingerprint while empty, so results computed before B11 stay current.
    unattributed_po_ids: tuple[str, ...] = field(default=(), metadata={"fingerprint": "omit_if_default"})


@dataclass(frozen=True)
class MatchInput:
    """Everything one evaluation needs, already scoped to the in-scope purchase orders.

    The input builder must not apply a date filter to purchase-order history,
    receipts or earlier invoices (CLAUDE.md, prohibited shortcuts).
    """

    tenant_currency: str
    test_document_ids: frozenset[str]
    documents: tuple[Document, ...]
    purchase_orders: tuple[PurchaseOrder, ...]
    aliases: tuple[Alias, ...] = ()
    receiving_imports: tuple[ReceivingImport, ...] = ()
    receipt_lines: tuple[ReceiptLine, ...] = ()
    qbo_bills: tuple[QboBill, ...] = ()
    default_tolerance: Tolerance = field(default_factory=Tolerance)
    vendor_tolerances: tuple[tuple[str, Tolerance], ...] = ()
    duplicate_decisions: tuple[tuple[str, DuplicateDecision], ...] = ()  # later doc id
    confirmed_not_received: frozenset[str] = frozenset()  # invoice line ids
    credit_decisions: tuple[CreditDecisionInput, ...] = ()  # B9; sorted by key
    ruleset_code: str = "v1"


@dataclass(frozen=True)
class ExceptionResult:
    type: ExceptionType
    document_id: str
    line_id: str | None
    value_class: ValueClass
    variance_amount: Decimal | None
    reported_amount: Decimal
    qualifying: bool
    status: ExceptionStatus = ExceptionStatus.OPEN
    sub_reason: SubReason | None = None
    variance_qty: Decimal | None = None
    resolution_code: ResolutionCode | None = None
    related_document_id: str | None = None
    related_qbo_bill_ids: tuple[str, ...] = ()
    possibly_credited_bill_id: str | None = None
    label: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        """Identity used for the stored fingerprint: (document, line or none, type)."""
        return (self.document_id, self.line_id or "", self.type.value)


@dataclass(frozen=True)
class LineResult:
    document_id: str
    line_id: str
    line_kind: LineKind
    status: LineStatus
    checks_run: tuple[str, ...]
    receipt_line_count: int
    po_line_id: str | None = None
    alias_id: str | None = None
    tolerance_rule_id: str | None = None
    qty_ordered: Decimal | None = None
    qty_received_cum: Decimal | None = None
    qty_invoiced_cum_net: Decimal | None = None
    qty_invoiced_prior_qbo: Decimal | None = None
    covered: bool | None = None
    po_unit_price: Decimal | None = None
    invoice_unit_price_po_uom: Decimal | None = None


@dataclass(frozen=True)
class MatchResult:
    ruleset_code: str
    lines: tuple[LineResult, ...]
    exceptions: tuple[ExceptionResult, ...]

    def line(self, line_id: str) -> LineResult:
        for item in self.lines:
            if item.line_id == line_id:
                return item
        raise KeyError(line_id)

    def exceptions_for(
        self, *, document_id: str | None = None, line_id: str | None = None
    ) -> list[ExceptionResult]:
        return [
            e
            for e in self.exceptions
            if (document_id is None or e.document_id == document_id)
            and (line_id is None or e.line_id == line_id)
        ]
