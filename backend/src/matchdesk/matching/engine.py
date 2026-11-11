"""Rule set v1: cumulative three-way match over open-PO history (TRD section 8.5).

``evaluate`` is a pure function of its input. It sorts every collection by a
deterministic key first, so the order in which documents, receipts or bills
arrived cannot change the result (MH-06, R-01, PT-01). Document order is
document date, normalised number, file hash; upload time is not an input.

Highest-consequence rules enforced here:

* ``receipt_absent`` is raised whenever a PO line has no counting receipt line.
  It has no tolerance input, it is never ``matched``, and it does not stop the
  ordered-quantity, price and duplicate checks (MH-07).
* QuickBooks quantities and class C documents never count as received (AD-05).
* Quantities are cumulative across partial deliveries, earlier invoices
  (uploaded or QuickBooks bills with no document) and credits (MH-06, MH-09).
* Duplicates are left out of cumulative quantities and reported once (MH-08).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from matchdesk.core import ZERO, dec, round_cents, round_price
from matchdesk.matching.fingerprint import assert_no_floats
from matchdesk.matching.normalise import (
    document_order_key,
    normalise_code,
    normalise_number,
    normalise_uom,
)
from matchdesk.matching.types import (
    Alias,
    AliasStatus,
    DocLine,
    DocType,
    Document,
    DuplicateDecision,
    EvidenceClass,
    ExceptionResult,
    ExceptionStatus,
    ExceptionType,
    LineKind,
    LineResult,
    LineStatus,
    MatchInput,
    MatchResult,
    PoLine,
    PurchaseOrder,
    QboBill,
    ReceiptLine,
    ReceivingImport,
    ResolutionCode,
    SubReason,
    Tolerance,
    ValueClass,
    VerificationStatus,
)

QBO_CREDIT_LABEL = "credited in QuickBooks, no document"
COVERAGE_DAYS_AFTER_INVOICE = 14
POSSIBLE_DUPLICATE_WINDOW_DAYS = 7
POSSIBLY_CREDITED_PCT = Decimal("0.01")
_HUNDRED = Decimal("100")

# Exception types whose amount is a finding candidate (Decision.md section 5.1).
_FINDING_TYPES = frozenset(
    {
        ExceptionType.QTY_OVER_RECEIVED,
        ExceptionType.QTY_OVER_ORDERED,
        ExceptionType.PRICE_VARIANCE,
        ExceptionType.DUPLICATE,
        ExceptionType.UNMATCHED_CHARGE,
    }
)
# Order in which finding-candidate amounts are counted against the line amount.
_FINDING_ORDER = {
    ExceptionType.RECEIPT_ABSENT: 0,
    ExceptionType.QTY_OVER_RECEIVED: 1,
    ExceptionType.QTY_OVER_ORDERED: 2,
    ExceptionType.PRICE_VARIANCE: 3,
}
_UNVERIFIED_ORDER = {
    ExceptionType.EXTRACTION_UNVERIFIED: 0,
    ExceptionType.NO_PO: 1,
    ExceptionType.ALIAS_UNCONFIRMED: 2,
    ExceptionType.PO_LINE_NOT_FOUND: 2,
    ExceptionType.UOM_UNRESOLVED: 3,
    ExceptionType.HISTORY_INCOMPLETE: 4,
    ExceptionType.RECEIPT_ABSENT: 5,
}


# --------------------------------------------------------------------------- helpers


def _doc_key(doc: Document) -> tuple:
    return (*document_order_key(doc.doc_date, doc.doc_number, doc.file_sha256), doc.id)


def _bill_key(bill: QboBill) -> tuple:
    # QuickBooks bills have no file; ``\xff`` sorts them after a document with the
    # same date and number, and the QuickBooks id breaks the remaining tie.
    return (*document_order_key(bill.txn_date, bill.doc_number, b"\xff"), bill.id)


def _is_verified(doc: Document) -> bool:
    return doc.verification in (
        VerificationStatus.PASSED,
        VerificationStatus.HUMAN_CONFIRMED,
        VerificationStatus.HUMAN_CONFIRMED_INCONSISTENT,
    )


def _line_amount(line: DocLine) -> Decimal:
    if line.amount is not None:
        return dec(line.amount)
    if line.qty is not None and line.unit_price is not None:
        return round_cents(dec(line.qty) * dec(line.unit_price))
    return ZERO


def receipt_line_counts(line: ReceiptLine, imp: ReceivingImport | None) -> bool:
    """Independent receiving evidence rule (TRD 8.5 "Counting receipt lines")."""
    if imp is None or not imp.committed or imp.voided:
        return False
    if imp.evidence_class == EvidenceClass.A:
        pass
    elif imp.evidence_class == EvidenceClass.B:
        if not line.receiver_marks_recorded:
            return False
    else:  # class C, or anything unknown, never counts
        return False
    return not (line.added_after_exception and not line.late_approved)


def is_covered(imports: tuple[ReceivingImport, ...], start: date, end: date) -> bool:
    """Class A logs declared complete, together, span every day from ``start`` to ``end``."""
    ranges = sorted(
        (i.coverage_start, i.coverage_end)
        for i in imports
        if i.evidence_class == EvidenceClass.A
        and i.declared_complete
        and i.committed
        and not i.voided
        and i.coverage_start is not None
        and i.coverage_end is not None
    )
    cursor = start
    for lo, hi in ranges:
        assert lo is not None and hi is not None
        if lo > cursor:
            break
        if hi >= cursor:
            cursor = hi + timedelta(days=1)
        if cursor > end:
            return True
    return cursor > end


def _tolerance_for(inp: MatchInput, vendor_id: str) -> Tolerance:
    for vid, tol in inp.vendor_tolerances:
        if vid == vendor_id:
            return tol
    return inp.default_tolerance


# --------------------------------------------------------------------------- state


@dataclass
class _Resolved:
    """An item line that passed checks 1 to 5."""

    doc: Document
    line: DocLine
    po: PurchaseOrder
    po_line: PoLine
    alias: Alias
    qty_po: Decimal
    price_po: Decimal
    order_key: tuple


@dataclass
class _QtyCredit:
    po_line_id: str
    qty: Decimal
    source_id: str
    applies_at: tuple | None  # order key of the referenced invoice; None = from the start
    label: str | None = None


@dataclass
class _PriceCredit:
    document_id: str  # the invoice it reduces
    amount: Decimal
    source_id: str
    label: str | None = None


@dataclass
class _State:
    exceptions: list[ExceptionResult] = field(default_factory=list)
    lines: dict[str, LineResult] = field(default_factory=dict)
    line_amounts: dict[str, Decimal] = field(default_factory=dict)


# --------------------------------------------------------------------------- evaluate


def evaluate(inp: MatchInput) -> MatchResult:
    assert_no_floats(inp)
    docs = sorted(inp.documents, key=_doc_key)
    pos = sorted(inp.purchase_orders, key=lambda p: p.id)
    imports = tuple(sorted(inp.receiving_imports, key=lambda i: i.id))
    imports_by_id = {i.id: i for i in imports}
    receipts = sorted(inp.receipt_lines, key=lambda r: r.id)
    bills = sorted(inp.qbo_bills, key=_bill_key)
    aliases = sorted(inp.aliases, key=lambda a: a.id)
    dup_decisions = dict(inp.duplicate_decisions)
    st = _State()

    po_by_number: dict[tuple[str, str], list[PurchaseOrder]] = defaultdict(list)
    for po in pos:
        po_by_number[(po.vendor_id, normalise_number(po.po_number))].append(po)

    # ---- document-level gates: check 1, currency, check 2 ----------------------------
    active: list[Document] = []  # documents whose lines feed matching and history
    stopped_at: dict[str, tuple[str, ...]] = {}
    for doc in docs:
        if not _is_verified(doc) or not doc.vendor_id:
            # A document whose vendor is not identified cannot be matched; it is an exception,
            # never silently dropped (B1-006).
            _doc_exception(st, doc, ExceptionType.EXTRACTION_UNVERIFIED, ValueClass.UNVERIFIED)
            stopped_at[doc.id] = ("1",)
            continue
        if doc.currency and doc.currency.upper() != inp.tenant_currency.upper():
            _doc_exception(st, doc, ExceptionType.CURRENCY_UNSUPPORTED, ValueClass.UNVERIFIED)
            stopped_at[doc.id] = ("1",)
            continue
        active.append(doc)

    duplicates: set[str] = set()
    seen_number: dict[tuple[str, str, str], Document] = {}
    for doc in active:
        norm = normalise_number(doc.doc_number)
        if not norm:
            continue
        k = (doc.vendor_id, doc.doc_type.value, norm)
        if k in seen_number:
            _doc_exception(
                st,
                doc,
                ExceptionType.DUPLICATE,
                _duplicate_class(doc),
                related_document_id=seen_number[k].id,
            )
            duplicates.add(doc.id)
        else:
            seen_number[k] = doc

    bills_by_number: dict[tuple[str, str], list[QboBill]] = defaultdict(list)
    for bill in bills:
        if bill.txn_type == "bill" and normalise_number(bill.doc_number):
            bills_by_number[(bill.vendor_id, normalise_number(bill.doc_number))].append(bill)
    for doc in active:
        if doc.id in duplicates or doc.doc_type != DocType.INVOICE:
            continue
        matching_bills = bills_by_number.get((doc.vendor_id, normalise_number(doc.doc_number)), [])
        if len(matching_bills) > 1:
            _doc_exception(
                st,
                doc,
                ExceptionType.DUPLICATE,
                ValueClass.FINDING_CANDIDATE,
                related_qbo_bill_ids=tuple(b.id for b in matching_bills),
            )
            duplicates.add(doc.id)

    kept: list[Document] = []
    for doc in active:
        if doc.id in duplicates:
            continue
        earlier = _possible_duplicate_of(doc, kept)
        if earlier is not None:
            decision = dup_decisions.get(doc.id)
            if decision == DuplicateDecision.CONFIRMED_DUPLICATE:
                _doc_exception(
                    st,
                    doc,
                    ExceptionType.DUPLICATE,
                    _duplicate_class(doc),
                    related_document_id=earlier.id,
                )
                duplicates.add(doc.id)
                continue
            if decision != DuplicateDecision.NOT_A_DUPLICATE:
                _doc_exception(
                    st,
                    doc,
                    ExceptionType.POSSIBLE_DUPLICATE,
                    ValueClass.OPEN_UNDECIDED if doc.doc_type == DocType.INVOICE else ValueClass.NONE,
                    related_document_id=earlier.id,
                )
                if doc.doc_type == DocType.CREDIT_NOTE:
                    # A credit that may be a second copy is not netted until a person decides,
                    # so one credit can never be netted twice (B1-003).
                    duplicates.add(doc.id)
                    continue
        kept.append(doc)
    for doc_id in duplicates:
        stopped_at[doc_id] = ("1", "2")

    invoices = [d for d in kept if d.doc_type == DocType.INVOICE]
    credit_docs = [d for d in kept if d.doc_type == DocType.CREDIT_NOTE]

    # ---- checks 3 to 5: purchase order, alias, unit ---------------------------------
    resolved: list[_Resolved] = []
    po_of_doc: dict[str, PurchaseOrder] = {}
    charge_cum: dict[tuple[str, LineKind], Decimal] = defaultdict(lambda: ZERO)
    for doc in invoices:
        found = po_by_number.get((doc.vendor_id, normalise_number(doc.po_number)), [])
        if len(found) != 1 or not normalise_number(doc.po_number):
            for line in doc.lines:
                _line_stop(st, doc, line, ("1", "2", "3"), ExceptionType.NO_PO)
            continue
        po = found[0]
        po_of_doc[doc.id] = po
        tol = _tolerance_for(inp, doc.vendor_id)
        for line in doc.lines:
            if line.kind != LineKind.ITEM:
                _charge_check(st, doc, line, po, tol, charge_cum)
                continue
            r = _resolve_line(st, doc, line, po, aliases)
            if r is not None:
                resolved.append(r)

    # ---- credits: credit notes and QuickBooks vendor credits (MH-09) ----------------
    qty_credits: list[_QtyCredit] = []
    price_credits: list[_PriceCredit] = []
    vendor_only_credits: list[QboBill] = []
    invoice_by_number = {
        (d.vendor_id, normalise_number(d.doc_number)): d for d in invoices if normalise_number(d.doc_number)
    }
    invoice_order = {d.id: _doc_key(d) for d in invoices}
    for cn in credit_docs:
        _link_credit_note(
            st,
            cn,
            inp,
            po_by_number,
            invoice_by_number,
            invoice_order,
            aliases,
            qty_credits,
            price_credits,
        )
    credit_doc_numbers = {(d.vendor_id, normalise_number(d.doc_number)) for d in credit_docs if d.doc_number}
    for bill in bills:
        if bill.txn_type != "vendor_credit":
            continue
        if (bill.vendor_id, normalise_number(bill.doc_number)) in credit_doc_numbers:
            continue  # the uploaded credit note represents it
        line_credits = [ln for ln in bill.lines if ln.po_line_id and ln.qty is not None]
        ref = (
            invoice_by_number.get((bill.vendor_id, normalise_number(bill.references_invoice_number)))
            if bill.references_invoice_number
            else None
        )
        if line_credits:
            for ln in sorted(line_credits, key=lambda x: x.id):
                assert ln.po_line_id is not None and ln.qty is not None
                qty_credits.append(
                    _QtyCredit(
                        ln.po_line_id,
                        abs(dec(ln.qty)),
                        bill.id,
                        invoice_order.get(ref.id) if ref else None,
                        QBO_CREDIT_LABEL,
                    )
                )
        elif ref is not None:
            price_credits.append(_PriceCredit(ref.id, abs(dec(bill.total)), bill.id, QBO_CREDIT_LABEL))
        else:
            vendor_only_credits.append(bill)

    # ---- invoiced history per PO line: documents and QuickBooks bills ---------------
    # A QuickBooks bill line is represented by an uploaded invoice only when that invoice's line
    # on the same PO line was resolved and counted (B1-002).
    counted = {
        (r.doc.vendor_id, normalise_number(r.doc.doc_number), r.po_line.id)
        for r in resolved
        if r.doc.doc_number
    }
    events: dict[str, list[tuple[tuple, Decimal, _Resolved | None]]] = defaultdict(list)
    prior_qbo: dict[str, list[tuple[tuple, Decimal]]] = defaultdict(list)
    for r in resolved:
        events[r.po_line.id].append((r.order_key, r.qty_po, r))
    for bill in bills:
        if bill.txn_type != "bill":
            continue
        for ln in bill.lines:
            if (bill.vendor_id, normalise_number(bill.doc_number), ln.po_line_id) in counted:
                continue  # an uploaded invoice line represents this bill line
            if ln.po_line_id and ln.qty is not None:
                events[ln.po_line_id].append((_bill_key(bill), dec(ln.qty), None))
                prior_qbo[ln.po_line_id].append((_bill_key(bill), dec(ln.qty)))

    gaps = _history_gaps(docs, active, duplicates, resolved, po_by_number, bills)

    receipts_by_po_line: dict[str, list[ReceiptLine]] = defaultdict(list)
    for rl in receipts:
        receipts_by_po_line[rl.po_line_id].append(rl)

    # ---- checks 6 to 10 on each resolved item line ----------------------------------
    for po_line_id, evs in events.items():
        evs.sort(key=lambda e: e[0])
        po_line_receipts = receipts_by_po_line.get(po_line_id, [])
        counting = [r for r in po_line_receipts if receipt_line_counts(r, imports_by_id.get(r.import_id))]
        received = sum((dec(r.qty_in_po_uom) for r in counting), ZERO)
        has_return = any(dec(r.qty_in_po_uom) < 0 for r in counting)
        class_c_only = not counting and any(
            (imp := imports_by_id.get(r.import_id)) is not None
            and imp.evidence_class == EvidenceClass.C
            and imp.committed
            and not imp.voided
            for r in po_line_receipts
        )
        known_invoiced = sum((q for _, q, _ in evs), ZERO)
        credits_here = [c for c in qty_credits if c.po_line_id == po_line_id]
        gross = ZERO
        for order_key, qty, r in evs:
            gross += qty
            if r is None:
                continue
            applicable = [c for c in credits_here if c.applies_at is None or c.applies_at <= order_key]
            net = gross - sum((c.qty for c in applicable), ZERO)
            prior_q = sum((q for k, q in prior_qbo.get(po_line_id, []) if k < order_key), ZERO)
            _evaluate_resolved(
                st,
                inp,
                r,
                counting_count=len(counting),
                received=received,
                has_return=has_return,
                class_c_only=class_c_only,
                known_invoiced=known_invoiced,
                gross=gross,
                net=net,
                applicable_credits=applicable,
                prior_qbo_qty=prior_q,
                imports=imports,
                history_gap=any(k < order_key for k in gaps.get(r.po.id, [])),
            )

    # ---- price-only credits, then possibly-credited flags ---------------------------
    _apply_price_credits(st, price_credits)
    _flag_possibly_credited(st, vendor_only_credits, {d.id: d for d in invoices})

    # ---- document-stopped lines ------------------------------------------------------
    for doc in docs:
        if doc.id in stopped_at:
            for line in doc.lines:
                _not_evaluated(st, doc, line, stopped_at[doc.id])
                st.line_amounts[line.id] = _line_amount(line)
        else:
            for line in doc.lines:
                st.line_amounts.setdefault(line.id, _line_amount(line))
                if line.id not in st.lines:
                    # credit-note lines are linked, not matched (checks 6-10 not run)
                    _not_evaluated(st, doc, line, ("1", "2"))

    excs = _assign_reported_amounts(st, docs)
    tests = inp.test_document_ids
    out_lines = tuple(
        sorted(
            (lr for lr in st.lines.values() if lr.document_id in tests),
            key=lambda x: (x.document_id, x.line_id),
        )
    )
    out_excs = tuple(sorted((e for e in excs if e.document_id in tests), key=lambda e: e.key))
    return MatchResult(ruleset_code=inp.ruleset_code, lines=out_lines, exceptions=out_excs)


# --------------------------------------------------------------------------- steps


def _possible_duplicate_of(doc: Document, kept: list[Document]) -> Document | None:
    if doc.total is None or doc.doc_date is None:
        return None
    for other in kept:
        if (
            other.vendor_id == doc.vendor_id
            and other.doc_type == doc.doc_type
            and other.total is not None
            and dec(other.total) == dec(doc.total)
            and other.doc_date is not None
            and abs((doc.doc_date - other.doc_date).days) <= POSSIBLE_DUPLICATE_WINDOW_DAYS
            and normalise_number(other.doc_number) != normalise_number(doc.doc_number)
        ):
            return other
    return None


def _doc_exception(
    st: _State,
    doc: Document,
    typ: ExceptionType,
    value_class: ValueClass,
    *,
    related_document_id: str | None = None,
    related_qbo_bill_ids: tuple[str, ...] = (),
) -> None:
    amount = dec(doc.total) if doc.total is not None else sum((_line_amount(ln) for ln in doc.lines), ZERO)
    st.exceptions.append(
        ExceptionResult(
            type=typ,
            document_id=doc.id,
            line_id=None,
            value_class=value_class,
            variance_amount=amount,
            reported_amount=ZERO,  # assigned at the end
            qualifying=False,
            related_document_id=related_document_id,
            related_qbo_bill_ids=related_qbo_bill_ids,
        )
    )


def _line_exception(
    st: _State,
    doc: Document,
    line: DocLine,
    typ: ExceptionType,
    value_class: ValueClass,
    variance: Decimal | None,
    **kw: object,
) -> None:
    st.exceptions.append(
        ExceptionResult(
            type=typ,
            document_id=doc.id,
            line_id=line.id,
            value_class=value_class,
            variance_amount=variance,
            reported_amount=ZERO,
            qualifying=False,
            **kw,  # type: ignore[arg-type]
        )
    )


def _not_evaluated(st: _State, doc: Document, line: DocLine, checks: tuple[str, ...]) -> None:
    st.lines[line.id] = LineResult(
        document_id=doc.id,
        line_id=line.id,
        line_kind=line.kind,
        status=LineStatus.NOT_EVALUATED,
        checks_run=checks,
        receipt_line_count=0,
    )


def _line_stop(
    st: _State,
    doc: Document,
    line: DocLine,
    checks: tuple[str, ...],
    typ: ExceptionType,
    *,
    po_line_id: str | None = None,
    alias_id: str | None = None,
) -> None:
    _line_exception(st, doc, line, typ, ValueClass.UNVERIFIED, _line_amount(line))
    st.lines[line.id] = LineResult(
        document_id=doc.id,
        line_id=line.id,
        line_kind=line.kind,
        status=LineStatus.EXCEPTION,
        checks_run=checks,
        receipt_line_count=0,
        po_line_id=po_line_id,
        alias_id=alias_id,
    )


def _find_alias(aliases: list[Alias], vendor_id: str, code: str | None) -> Alias | None:
    norm = normalise_code(code)
    if not norm:
        return None
    candidates = [
        a
        for a in aliases
        if a.vendor_id == vendor_id
        and normalise_code(a.supplier_item_code) == norm
        and a.status in (AliasStatus.ACTIVE, AliasStatus.PENDING_APPROVAL)
    ]
    # An active alias wins over a pending one; ids break any remaining tie.
    candidates.sort(key=lambda a: (a.status != AliasStatus.ACTIVE, a.id))
    return candidates[0] if candidates else None


def alias_converts(alias: Alias) -> bool:
    """An alias converts when its factor is not 1 or its supplier and item units differ.

    A converting alias needs the controller's approval before any line passes (MH-10, B1-008).
    """
    sup, item = normalise_uom(alias.supplier_uom), normalise_uom(alias.item_uom)
    return dec(alias.conversion_factor) != 1 or (sup is not None and item is not None and sup != item)


def _duplicate_class(doc: Document) -> ValueClass:
    """A duplicate invoice is a finding worth its total; a duplicate credit note is not money owed (B1-003)."""
    return ValueClass.FINDING_CANDIDATE if doc.doc_type == DocType.INVOICE else ValueClass.NONE


def _history_gaps(
    docs: list[Document],
    active: list[Document],
    duplicates: set[str],
    resolved: list[_Resolved],
    po_by_number: dict[tuple[str, str], list[PurchaseOrder]],
    bills: list[QboBill],
) -> dict[str, list[tuple]]:
    """Order keys of invoices on each PO with an item line whose quantity is unknown (B1-002).

    An invoice line that stopped at check 1, 4 or 5 (or lacks a quantity) adds an unknown quantity
    to some line of its PO, unless a QuickBooks bill with the same number has lines linked to that
    PO, in which case those bill lines count instead.
    """
    active_ids = {d.id for d in active}
    resolved_ids = {r.line.id for r in resolved}
    gaps: dict[str, list[tuple]] = defaultdict(list)
    for doc in docs:
        if doc.doc_type != DocType.INVOICE or doc.id in duplicates or not doc.vendor_id:
            continue
        found = po_by_number.get((doc.vendor_id, normalise_number(doc.po_number)), [])
        if len(found) != 1:
            continue
        po = found[0]
        unresolved = [
            ln
            for ln in doc.lines
            if ln.kind == LineKind.ITEM and (doc.id not in active_ids or ln.id not in resolved_ids)
        ]
        if not unresolved:
            continue
        po_line_ids = {pl.id for pl in po.lines}
        represented = any(
            b.txn_type == "bill"
            and b.vendor_id == doc.vendor_id
            and normalise_number(b.doc_number) == normalise_number(doc.doc_number)
            and any(bl.po_line_id in po_line_ids for bl in b.lines)
            for b in bills
        )
        if not represented:
            gaps[po.id].append(_doc_key(doc))
    return gaps


def _conversion(line: DocLine, po_line: PoLine, alias: Alias) -> Decimal | None:
    """Item units per invoice unit, or None when the unit cannot be converted (check 5)."""
    inv_uom = normalise_uom(line.uom)
    po_uom = normalise_uom(po_line.uom)
    if inv_uom is None:
        # No unit on the invoice: assume the PO unit only when the alias does not convert (B1-008).
        sup = normalise_uom(alias.supplier_uom)
        return Decimal("1") if (sup is None or sup == po_uom) and not alias_converts(alias) else None
    if inv_uom == po_uom:
        return Decimal("1")
    if inv_uom == normalise_uom(alias.supplier_uom) and normalise_uom(alias.item_uom) == po_uom:
        return dec(alias.conversion_factor)
    return None


def _resolve_line(
    st: _State, doc: Document, line: DocLine, po: PurchaseOrder, aliases: list[Alias]
) -> _Resolved | None:
    if line.qty is None or line.unit_price is None:
        _line_stop(st, doc, line, ("1", "2", "3"), ExceptionType.EXTRACTION_UNVERIFIED)
        return None
    alias = _find_alias(aliases, doc.vendor_id, line.supplier_item_code)
    usable = (
        alias is not None
        and alias.status == AliasStatus.ACTIVE
        and (not alias_converts(alias) or alias.approved)
    )
    if alias is None or not usable:
        _line_stop(
            st,
            doc,
            line,
            ("1", "2", "3", "4"),
            ExceptionType.ALIAS_UNCONFIRMED,
            alias_id=alias.id if alias else None,
        )
        return None
    item_lines = [pl for pl in po.lines if pl.item_id == alias.item_id and pl.charge_kind is None]
    if len(item_lines) != 1:
        _line_stop(st, doc, line, ("1", "2", "3", "4"), ExceptionType.PO_LINE_NOT_FOUND, alias_id=alias.id)
        return None
    po_line = item_lines[0]
    factor = _conversion(line, po_line, alias)
    if factor is None or factor <= 0:
        _line_stop(
            st,
            doc,
            line,
            ("1", "2", "3", "4", "5"),
            ExceptionType.UOM_UNRESOLVED,
            po_line_id=po_line.id,
            alias_id=alias.id,
        )
        return None
    return _Resolved(
        doc=doc,
        line=line,
        po=po,
        po_line=po_line,
        alias=alias,
        qty_po=dec(line.qty) * factor,
        price_po=round_price(dec(line.unit_price) / factor),
        order_key=_doc_key(doc),
    )


def _charge_check(
    st: _State,
    doc: Document,
    line: DocLine,
    po: PurchaseOrder,
    tol: Tolerance,
    charge_cum: dict[tuple[str, LineKind], Decimal],
) -> None:
    """Check C1 for freight, fee and discount lines, cumulatively per PO and charge kind (B1-005).

    Charges of one kind billed on the PO's invoices, in document order, may total at most the
    PO's charge lines of that kind plus the vendor's charge allowance (applied once per PO).
    The excess on each line is ``unmatched_charge``.
    """
    amount = _line_amount(line)
    excess = ZERO
    if line.kind != LineKind.DISCOUNT and amount > 0:
        limit = sum(
            (dec(pl.amount) for pl in po.lines if pl.charge_kind == line.kind and pl.amount is not None),
            ZERO,
        ) + dec(tol.charge_allowance)
        key = (po.id, line.kind)
        charge_cum[key] += amount
        excess = min(amount, max(ZERO, charge_cum[key] - limit))
    ok = excess <= 0
    if not ok:
        _line_exception(st, doc, line, ExceptionType.UNMATCHED_CHARGE, ValueClass.FINDING_CANDIDATE, excess)
    st.lines[line.id] = LineResult(
        document_id=doc.id,
        line_id=line.id,
        line_kind=line.kind,
        status=LineStatus.CHARGE_OK if ok else LineStatus.EXCEPTION,
        checks_run=("1", "2", "3", "C1"),
        receipt_line_count=0,
        tolerance_rule_id=tol.rule_id,
    )


def _link_credit_note(
    st: _State,
    cn: Document,
    inp: MatchInput,
    po_by_number: dict[tuple[str, str], list[PurchaseOrder]],
    invoice_by_number: dict[tuple[str, str], Document],
    invoice_order: dict[str, tuple],
    aliases: list[Alias],
    qty_credits: list[_QtyCredit],
    price_credits: list[_PriceCredit],
) -> None:
    ref = None
    if cn.references_invoice_number:
        ref = invoice_by_number.get((cn.vendor_id, normalise_number(cn.references_invoice_number)))
    po: PurchaseOrder | None = None
    po_number = ref.po_number if ref is not None else cn.po_number
    found = po_by_number.get((cn.vendor_id, normalise_number(po_number)), [])
    if len(found) == 1:
        po = found[0]
    if ref is None and po is None:
        _doc_exception(st, cn, ExceptionType.CREDIT_UNLINKED, ValueClass.NONE)
        return
    applies_at = invoice_order.get(ref.id) if ref is not None else None
    for line in sorted(cn.lines, key=lambda x: (x.line_no, x.id)):
        amount = abs(_line_amount(line))
        if line.qty is not None and line.kind == LineKind.ITEM and po is not None:
            alias = _find_alias(aliases, cn.vendor_id, line.supplier_item_code)
            usable = (
                alias is not None
                and alias.status == AliasStatus.ACTIVE
                and (not alias_converts(alias) or alias.approved)
            )
            if alias is not None and usable:
                pls = [pl for pl in po.lines if pl.item_id == alias.item_id and pl.charge_kind is None]
                if len(pls) == 1:
                    factor = _conversion(line, pls[0], alias)
                    if factor is not None and factor > 0:
                        qty_credits.append(
                            _QtyCredit(pls[0].id, abs(dec(line.qty)) * factor, cn.id, applies_at)
                        )
                        continue
            _line_exception(st, cn, line, ExceptionType.CREDIT_UNLINKED, ValueClass.NONE, amount)
        elif ref is not None:
            price_credits.append(_PriceCredit(ref.id, amount, cn.id))
        else:
            _line_exception(st, cn, line, ExceptionType.CREDIT_UNLINKED, ValueClass.NONE, amount)


def _evaluate_resolved(
    st: _State,
    inp: MatchInput,
    r: _Resolved,
    *,
    counting_count: int,
    received: Decimal,
    has_return: bool,
    class_c_only: bool,
    known_invoiced: Decimal,
    gross: Decimal,
    net: Decimal,
    applicable_credits: list[_QtyCredit],
    prior_qbo_qty: Decimal,
    imports: tuple[ReceivingImport, ...],
    history_gap: bool = False,
) -> None:
    doc, line, pl = r.doc, r.line, r.po_line
    tol = _tolerance_for(inp, doc.vendor_id)
    checks = ["1", "2", "3", "4", "5", "6"]
    # Check 6: QuickBooks billed quantity not explained by known invoices (does not stop).
    billed_unexplained = pl.qbo_billed_qty is not None and dec(pl.qbo_billed_qty) > known_invoiced
    if history_gap and not billed_unexplained:
        # An earlier invoice on this PO has a line that could not be resolved to a PO line and no
        # QuickBooks bill line stands in for it: its quantity is unknown, so this line cannot pass.
        _line_exception(
            st, doc, line, ExceptionType.HISTORY_INCOMPLETE, ValueClass.UNVERIFIED, _line_amount(line)
        )
    if billed_unexplained:
        assert pl.qbo_billed_qty is not None
        _line_exception(
            st,
            doc,
            line,
            ExceptionType.HISTORY_INCOMPLETE,
            ValueClass.UNVERIFIED,
            _line_amount(line),
            variance_qty=dec(pl.qbo_billed_qty) - known_invoiced,
        )
    # Check 7: at least one counting receipt line. No tolerance; no setting disables it.
    checks.append("7")
    inv_date = doc.doc_date or r.po.txn_date
    covered = is_covered(imports, r.po.txn_date, inv_date + timedelta(days=COVERAGE_DAYS_AFTER_INVOICE))
    if counting_count == 0 or received <= 0:
        # No counting receipt, or receipts that net to nothing kept: receipt_absent whatever the
        # tolerance (B1-004).
        if line.id in inp.confirmed_not_received:
            _line_exception(
                st,
                doc,
                line,
                ExceptionType.RECEIPT_ABSENT,
                ValueClass.FINDING_CANDIDATE,
                _line_amount(line),
                sub_reason=SubReason.NOT_RECEIVED
                if covered
                else (SubReason.SUPPLIER_SLIP_ONLY if class_c_only else SubReason.NO_EVIDENCE),
                status=ExceptionStatus.RESOLVED,
                resolution_code=ResolutionCode.CONFIRMED_NOT_RECEIVED,
            )
        elif covered:
            _line_exception(
                st,
                doc,
                line,
                ExceptionType.RECEIPT_ABSENT,
                ValueClass.FINDING_CANDIDATE,
                _line_amount(line),
                sub_reason=SubReason.NOT_RECEIVED,
            )
        else:
            _line_exception(
                st,
                doc,
                line,
                ExceptionType.RECEIPT_ABSENT,
                ValueClass.UNVERIFIED,
                _line_amount(line),
                sub_reason=SubReason.SUPPLIER_SLIP_ONLY if class_c_only else SubReason.NO_EVIDENCE,
            )
    else:
        # Check 8: cumulative invoiced (net of credits) <= cumulative received + tolerance.
        checks.append("8")
        _qty_check(
            st,
            r,
            ExceptionType.QTY_OVER_RECEIVED,
            received + dec(tol.qty_tolerance),
            gross,
            net,
            applicable_credits,
            sub_reason=SubReason.RETURNED_NO_CREDIT if has_return else None,
        )
    # Check 9: cumulative invoiced <= ordered + tolerance.
    checks.append("9")
    _qty_check(
        st,
        r,
        ExceptionType.QTY_OVER_ORDERED,
        dec(pl.qty_ordered) + dec(tol.qty_tolerance),
        gross,
        net,
        applicable_credits,
    )
    # Check 10: price.
    checks.append("10")
    po_price = dec(pl.unit_price)
    diff = r.price_po - po_price
    allowed = max(dec(tol.price_tol_abs), dec(tol.price_tol_pct) / _HUNDRED * po_price)
    if diff > allowed:
        _line_exception(
            st,
            doc,
            line,
            ExceptionType.PRICE_VARIANCE,
            ValueClass.FINDING_CANDIDATE,
            round_cents(diff * r.qty_po),
        )
    line_excs = [e for e in st.exceptions if e.line_id == line.id and e.document_id == doc.id]
    blocking = [
        e for e in line_excs if e.status == ExceptionStatus.OPEN or e.type == ExceptionType.RECEIPT_ABSENT
    ]
    matched = not blocking and counting_count > 0 and received > 0
    st.lines[line.id] = LineResult(
        document_id=doc.id,
        line_id=line.id,
        line_kind=line.kind,
        status=LineStatus.MATCHED if matched else LineStatus.EXCEPTION,
        checks_run=tuple(checks),
        receipt_line_count=counting_count,
        po_line_id=pl.id,
        alias_id=r.alias.id,
        tolerance_rule_id=tol.rule_id,
        qty_ordered=dec(pl.qty_ordered),
        qty_received_cum=received if counting_count else ZERO,
        qty_invoiced_cum_net=net,
        qty_invoiced_prior_qbo=prior_qbo_qty,
        covered=covered,
        po_unit_price=po_price,
        invoice_unit_price_po_uom=r.price_po,
    )


def _qty_check(
    st: _State,
    r: _Resolved,
    typ: ExceptionType,
    limit: Decimal,
    gross: Decimal,
    net: Decimal,
    credits: list[_QtyCredit],
    sub_reason: SubReason | None = None,
) -> None:
    """Excess attributable to this line: min(line qty, cumulative - limit), net of credits."""
    excess_net = min(r.qty_po, max(ZERO, net - limit))
    excess_gross = min(r.qty_po, max(ZERO, gross - limit))
    if excess_net > 0:
        _line_exception(
            st,
            r.doc,
            r.line,
            typ,
            ValueClass.FINDING_CANDIDATE,
            round_cents(excess_net * r.price_po),
            variance_qty=excess_net,
            sub_reason=sub_reason,
        )
    elif excess_gross > 0 and credits:
        source = sorted(credits, key=lambda c: (c.applies_at is None, c.applies_at or (), c.source_id))[-1]
        _line_exception(
            st,
            r.doc,
            r.line,
            typ,
            ValueClass.FINDING_CANDIDATE,
            round_cents(excess_gross * r.price_po),
            variance_qty=excess_gross,
            status=ExceptionStatus.RESOLVED,
            resolution_code=ResolutionCode.RESOLVED_BY_CREDIT,
            related_document_id=source.source_id,
            label=source.label,
        )


def _apply_price_credits(st: _State, credits: list[_PriceCredit]) -> None:
    remaining: dict[str, list[_PriceCredit]] = defaultdict(list)
    for c in sorted(credits, key=lambda c: c.source_id):
        remaining[c.document_id].append(_PriceCredit(c.document_id, c.amount, c.source_id, c.label))
    if not remaining:
        return
    order = {ExceptionType.PRICE_VARIANCE: 0, ExceptionType.UNMATCHED_CHARGE: 1}
    targets = sorted(
        (
            (i, e)
            for i, e in enumerate(st.exceptions)
            if e.type in order and e.status == ExceptionStatus.OPEN and e.document_id in remaining
        ),
        key=lambda t: (order[t[1].type], t[1].line_id or ""),
    )
    for idx, exc in targets:
        pool = remaining[exc.document_id]
        variance = exc.variance_amount or ZERO
        used: list[str] = []
        labels: list[str | None] = []
        for c in pool:
            if variance <= 0:
                break
            take = min(c.amount, variance)
            if take > 0:
                c.amount -= take
                variance -= take
                used.append(c.source_id)
                labels.append(c.label)
        if not used:
            continue
        if variance <= 0:
            st.exceptions[idx] = replace(
                exc,
                status=ExceptionStatus.RESOLVED,
                resolution_code=ResolutionCode.RESOLVED_BY_CREDIT,
                related_document_id=used[-1],
                label=labels[-1],
            )
        else:
            st.exceptions[idx] = replace(
                exc, variance_amount=variance, related_document_id=used[-1], label=labels[-1]
            )


def _flag_possibly_credited(st: _State, credits: list[QboBill], invoices: dict[str, Document]) -> None:
    for credit in credits:
        amount = abs(dec(credit.total))
        for idx, exc in enumerate(st.exceptions):
            doc = invoices.get(exc.document_id)
            if (
                doc is None
                or exc.status != ExceptionStatus.OPEN
                or exc.value_class != ValueClass.FINDING_CANDIDATE
                or exc.variance_amount is None
                or exc.variance_amount <= 0
                or doc.vendor_id != credit.vendor_id
                or credit.txn_date is None
                or doc.doc_date is None
                or credit.txn_date <= doc.doc_date
            ):
                continue
            if abs(amount - exc.variance_amount) <= POSSIBLY_CREDITED_PCT * exc.variance_amount:
                st.exceptions[idx] = replace(
                    exc, value_class=ValueClass.OPEN_UNDECIDED, possibly_credited_bill_id=credit.id
                )


def _assign_reported_amounts(st: _State, docs: list[Document]) -> list[ExceptionResult]:
    """Per-line reported amounts that add up to no more than the line amount (TRD 8.5)."""
    out: list[ExceptionResult] = []
    by_line: dict[str, list[ExceptionResult]] = defaultdict(list)
    for e in st.exceptions:
        if e.line_id is None:
            counts = e.status == ExceptionStatus.OPEN
            amount = e.variance_amount or ZERO
            reported = amount if counts and e.value_class != ValueClass.NONE else ZERO
            out.append(_finalise(e, reported))
        else:
            by_line[e.line_id].append(e)
    for line_id in sorted(by_line):
        excs = by_line[line_id]
        line_amount = st.line_amounts.get(line_id, ZERO)
        counted = ZERO
        finding_like = sorted(
            (e for e in excs if e.value_class in (ValueClass.FINDING_CANDIDATE, ValueClass.OPEN_UNDECIDED)),
            key=lambda e: _FINDING_ORDER.get(e.type, 9),
        )
        # Where checks 8 and 9 both fail on one line, one amount is reported: the larger.
        over = [
            e
            for e in finding_like
            if e.type in (ExceptionType.QTY_OVER_RECEIVED, ExceptionType.QTY_OVER_ORDERED)
            and e.status == ExceptionStatus.OPEN
        ]
        suppressed: set[int] = set()
        if len(over) == 2:
            # Tie: qty_over_received carries the amount (explicit priority, TRD 8.5).
            smaller = min(
                over, key=lambda e: (e.variance_amount or ZERO, e.type != ExceptionType.QTY_OVER_ORDERED)
            )
            suppressed.add(id(smaller))
        for e in finding_like:
            active = e.status == ExceptionStatus.OPEN or (
                e.resolution_code == ResolutionCode.CONFIRMED_NOT_RECEIVED
            )
            if not active or id(e) in suppressed:
                out.append(_finalise(e, ZERO))
                continue
            take = max(ZERO, min(e.variance_amount or ZERO, line_amount - counted))
            counted += take
            out.append(_finalise(e, take))
        unverified = sorted(
            (e for e in excs if e.value_class == ValueClass.UNVERIFIED),
            key=lambda e: _UNVERIFIED_ORDER.get(e.type, 9),
        )
        first = True
        for e in unverified:
            take = max(ZERO, line_amount - counted) if first else ZERO
            first = False
            out.append(_finalise(e, take))
        for e in excs:
            if e.value_class == ValueClass.NONE:
                out.append(_finalise(e, ZERO))
    return out


def _finalise(e: ExceptionResult, reported: Decimal) -> ExceptionResult:
    reported = round_cents(reported)
    removed_by_evidence = e.resolution_code == ResolutionCode.RESOLVED_BY_CREDIT
    finding = e.value_class == ValueClass.FINDING_CANDIDATE and not removed_by_evidence
    qualifying = finding and (
        e.type in _FINDING_TYPES
        or (
            e.type == ExceptionType.RECEIPT_ABSENT
            and (
                e.sub_reason == SubReason.NOT_RECEIVED
                or e.resolution_code == ResolutionCode.CONFIRMED_NOT_RECEIVED
            )
        )
    )
    variance = round_cents(e.variance_amount) if e.variance_amount is not None else None
    return replace(e, reported_amount=reported, qualifying=qualifying, variance_amount=variance)
