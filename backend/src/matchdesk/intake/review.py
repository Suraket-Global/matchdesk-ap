"""Extraction review: values with provenance, human correction, conflict handling, confirmation
(T-3.3.3 back end; MH-05; IT-14 for documents).

A correction records, per field, ``edited`` with who, when and the value that was read, and sets the
document back to unconfirmed: an edited document is matched again only after a person confirms it.
Confirmation re-runs the deterministic gates on the stored values: ``human_confirmed`` when they
hold, ``human_confirmed_inconsistent`` only when the person explicitly accepts the failing gates.
Every write checks the record version; a mismatch is a conflict carrying the current record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, dec
from matchdesk.extraction import verification_gates
from matchdesk.extraction.models import ExtractionRunRow
from matchdesk.intake.documents import identify_vendor, link_po
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.matching import normalise_number
from matchdesk.qbo.models import Vendor
from matchdesk.tenancy import lock_for_update, transition

EDITABLE_HEADER = (
    "doc_type",
    "vendor_id",
    "doc_number",
    "doc_date",
    "po_number_read",
    "currency",
    "subtotal",
    "tax_total",
    "total",
    "references_invoice_number",
)
EDITABLE_LINE = ("supplier_item_code", "description", "qty", "uom", "unit_price", "amount", "line_kind")
MONEY_FIELDS = {"subtotal", "tax_total", "total", "amount"}
DECIMAL_FIELDS = {"qty", "unit_price"} | MONEY_FIELDS


class VersionConflict(ConflictError):
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("stale version")
        self.current = current


def _plain(value: Any) -> Any:
    if isinstance(value, (Decimal, date, uuid.UUID)):
        return str(value)
    return value


def _coerce(name: str, value: Any) -> Any:
    if value is None or value == "":
        return None
    if name in DECIMAL_FIELDS:
        return dec(str(value))
    if name == "doc_date":
        return date.fromisoformat(str(value))
    if name == "vendor_id":
        return uuid.UUID(str(value))
    if name == "doc_type" and value not in ("invoice", "credit_note"):
        raise ValueError("doc_type must be invoice or credit_note")
    if name == "line_kind" and value not in ("item", "freight", "fee", "discount"):
        raise ValueError("line_kind must be item, freight, fee or discount")
    return str(value)


def lines_of(s: Session, invoice_id: uuid.UUID) -> list[InvoiceLineRow]:
    return list(
        s.scalars(
            select(InvoiceLineRow)
            .where(InvoiceLineRow.invoice_id == invoice_id, InvoiceLineRow.removed_at.is_(None))
            .order_by(InvoiceLineRow.line_no)
        ).all()
    )


def removed_lines_of(s: Session, invoice_id: uuid.UUID) -> list[InvoiceLineRow]:
    """Lines removed in review, kept as history (B9)."""
    return list(
        s.scalars(
            select(InvoiceLineRow)
            .where(InvoiceLineRow.invoice_id == invoice_id, InvoiceLineRow.removed_at.is_not(None))
            .order_by(InvoiceLineRow.removed_at, InvoiceLineRow.line_no)
        ).all()
    )


def describe_fields(s: Session, inv: InvoiceRow) -> dict[str, Any]:
    """Header and line values with provenance, document state, gates and the server-side draft."""
    doc = s.get(DocumentRow, inv.document_id)
    run = s.get(ExtractionRunRow, inv.extraction_run_id) if inv.extraction_run_id else None
    return {
        "document_id": str(inv.document_id),
        "document_state": doc.state if doc else None,
        "verification_status": inv.verification_status,
        "verification": run.verification if run else None,
        "extraction": {"provider": run.provider, "model": run.model, "prompt_version": run.prompt_version}
        if run
        else None,
        "fields": {f: _plain(getattr(inv, f)) for f in EDITABLE_HEADER},
        "vendor_name_read": inv.vendor_name_read,
        "purchase_order_id": str(inv.purchase_order_id) if inv.purchase_order_id else None,
        "field_sources": inv.field_sources or {},
        "review_draft": inv.review_draft,
        "confirmed_by": str(inv.confirmed_by) if inv.confirmed_by else None,
        "confirmed_at": inv.confirmed_at.isoformat() if inv.confirmed_at else None,
        "line_fields": [
            {
                "line_no": ln.line_no,
                "id": str(ln.id),
                **{f: _plain(getattr(ln, f)) for f in EDITABLE_LINE},
                "page_no": ln.page_no,
                "field_sources": ln.field_sources or {},
            }
            for ln in lines_of(s, inv.id)
        ],
        "removed_lines": [
            {
                "line_no": ln.line_no,
                "id": str(ln.id),
                **{f: _plain(getattr(ln, f)) for f in EDITABLE_LINE},
                "removed_by": str(ln.removed_by) if ln.removed_by else None,
                "removed_at": ln.removed_at.isoformat() if ln.removed_at else None,
                "removed_reason": ln.removed_reason,
            }
            for ln in removed_lines_of(s, inv.id)
        ],
        "next_line_no": _next_line_no(s, inv.id),
        "inconsistent_note": inv.inconsistent_note,
        "version": inv.version,
    }


def _next_line_no(s: Session, invoice_id: uuid.UUID) -> int:
    """A new line never reuses the number of a removed one (the number stays in its history)."""
    used = s.scalars(select(InvoiceLineRow.line_no).where(InvoiceLineRow.invoice_id == invoice_id)).all()
    return max(used, default=0) + 1


def _check_version(s: Session, inv: InvoiceRow, expected: int) -> None:
    lock_for_update(s, inv)  # B3/B4 review M3: compare the version under a row lock
    if inv.version != expected:
        raise VersionConflict(describe_fields(s, inv))


def _edited(by: uuid.UUID, original: Any) -> dict[str, Any]:
    return {
        "source": "edited",
        "by": str(by),
        "at": datetime.now(UTC).isoformat(),
        "original": _plain(original),
    }


def _original(sources: dict | None, name: str, current: Any) -> Any:
    """The value first read, kept across repeated edits."""
    prev = (sources or {}).get(name, {})
    return prev.get("original") if prev.get("source") == "edited" else current


def correct(
    s: Session,
    inv: InvoiceRow,
    user_id: uuid.UUID,
    expected_version: int,
    fields: dict[str, Any],
    lines: list[dict[str, Any]],
    draft: bool = False,
) -> InvoiceRow:
    """Save a draft (``draft=True``: kept on the server, values unchanged) or apply corrections."""
    _check_version(s, inv, expected_version)
    unknown = set(fields) - set(EDITABLE_HEADER)
    if unknown:
        raise ValueError("not editable: " + ", ".join(sorted(unknown)))
    if draft:
        inv.review_draft = {
            "fields": {k: _plain(v) for k, v in fields.items()},
            "lines": lines,
            "saved_by": str(user_id),
            "saved_at": datetime.now(UTC).isoformat(),
        }
        inv.version += 1
        s.flush()
        return inv
    sources = dict(inv.field_sources or {})
    changed: list[str] = []
    for name, raw in fields.items():
        value = _coerce(name, raw)
        if name == "vendor_id" and value is not None and s.get(Vendor, value) is None:
            raise ValueError("unknown vendor")
        if getattr(inv, name) != value:
            sources[name] = _edited(user_id, _original(inv.field_sources, name, getattr(inv, name)))
            setattr(inv, name, value)
            changed.append(name)
    if "doc_number" in changed:
        inv.doc_number_norm = normalise_number(inv.doc_number) or None
    if "vendor_id" in changed or "po_number_read" in changed:
        inv.purchase_order_id = link_po(s, inv.vendor_id, inv.po_number_read)
    inv.field_sources = sources
    existing = {ln.line_no: ln for ln in lines_of(s, inv.id)}
    removed_nos = {ln.line_no for ln in removed_lines_of(s, inv.id)}
    for spec in lines:
        line_no = int(spec["line_no"])
        unknown_l = set(spec) - set(EDITABLE_LINE) - {"line_no"}
        if unknown_l:
            raise ValueError("not editable on a line: " + ", ".join(sorted(unknown_l)))
        ln = existing.get(line_no)
        if ln is None and line_no in removed_nos:
            raise ValueError(f"line {line_no} was removed; add a new line with another number")
        if ln is None:
            ln = InvoiceLineRow(
                tenant_id=inv.tenant_id,
                invoice_id=inv.id,
                line_no=line_no,
                field_sources={},
                line_kind="item",
            )
            s.add(ln)
        lsources = dict(ln.field_sources or {})
        for name, raw in spec.items():
            if name == "line_no":
                continue
            value = _coerce(name, raw)
            if getattr(ln, name) != value:
                lsources[name] = _edited(user_id, _original(ln.field_sources, name, getattr(ln, name)))
                setattr(ln, name, value)
                changed.append(f"line {line_no}.{name}")
        ln.field_sources = lsources
    if changed:
        # An edited document waits for confirmation before it is matched again (MH-05).
        inv.verification_status = "failed"
        inv.confirmed_by, inv.confirmed_at = None, None
        doc = s.get(DocumentRow, inv.document_id)
        if doc is not None and doc.state == "succeeded":
            transition(s, "documents", doc.id, doc.state_version, "needs_review")
    inv.review_draft = None
    inv.version += 1
    s.flush()
    write_audit(
        s,
        inv.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="invoice.corrected",
        entity_type="invoice",
        entity_id=inv.id,
        after={"fields": changed},
    )
    return inv


def current_gates(s: Session, inv: InvoiceRow) -> dict[str, bool]:
    lines = lines_of(s, inv.id)
    output = {
        "lines": [
            {"qty": ln.qty, "unit_price": ln.unit_price, "amount": ln.amount or Decimal("0")} for ln in lines
        ],
        "tax_total": inv.tax_total or Decimal("0"),
        "total": inv.total or Decimal("0"),
    }
    if inv.subtotal is not None:
        output["subtotal"] = inv.subtotal
    gates = verification_gates(output)
    gates["vendor_identified"] = inv.vendor_id is not None
    gates["number_date_total_present"] = bool(inv.doc_number and inv.doc_date and inv.total is not None)
    gates["has_lines"] = bool(lines)
    return gates


def confirm(
    s: Session,
    inv: InvoiceRow,
    user_id: uuid.UUID,
    expected_version: int,
    accept_inconsistent: bool = False,
    note: str | None = None,
) -> tuple[InvoiceRow, dict[str, bool]]:
    _check_version(s, inv, expected_version)
    if inv.vendor_id is None:
        inv.vendor_id = identify_vendor(s, inv.vendor_name_read)
        inv.purchase_order_id = link_po(s, inv.vendor_id, inv.po_number_read)
    gates = current_gates(s, inv)
    identity_ok = gates["vendor_identified"] and gates["number_date_total_present"] and gates["has_lines"]
    if not identity_ok:
        raise ValueError("vendor, number, date, total and at least one line are required before confirming")
    arithmetic_ok = all(
        v
        for k, v in gates.items()
        if k not in ("vendor_identified", "number_date_total_present", "has_lines")
    )
    if not arithmetic_ok and not accept_inconsistent:
        raise ValueError("the amounts do not add up; correct them or confirm as inconsistent")
    clean_note = (note or "").strip() or None
    if not arithmetic_ok and clean_note is None:
        # S-07 (B9): "The document itself does not add up" needs the clerk's note, kept with the
        # document, shown in its history and carried into the report.
        raise ValueError("say in a note why the document itself does not add up")
    inv.verification_status = "human_confirmed" if arithmetic_ok else "human_confirmed_inconsistent"
    inv.inconsistent_note = None if arithmetic_ok else clean_note
    inv.confirmed_by, inv.confirmed_at = user_id, datetime.now(UTC)
    inv.review_draft = None
    inv.version += 1
    doc = s.get(DocumentRow, inv.document_id)
    if doc is not None and doc.state == "needs_review":
        transition(s, "documents", doc.id, doc.state_version, "succeeded")
    s.flush()
    write_audit(
        s,
        inv.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="invoice.confirmed",
        entity_type="invoice",
        entity_id=inv.id,
        after={
            "status": inv.verification_status,
            "gates": gates,
            **({"note": inv.inconsistent_note} if inv.inconsistent_note else {}),
        },
    )
    return inv, gates


def remove_line(
    s: Session,
    inv: InvoiceRow,
    user_id: uuid.UUID,
    expected_version: int,
    line_id: uuid.UUID,
    reason: str | None,
) -> tuple[InvoiceRow, dict[str, bool]]:
    """Remove one line in review (S-07; B9). A soft removal: the row stays with who, when and why,
    its earlier results stay as superseded history, and the arithmetic gates are run again on the
    remaining lines. Only before a person confirmed the document; like any edit it then waits for
    confirmation before it is matched again (MH-05)."""
    _check_version(s, inv, expected_version)
    if inv.verification_status in ("human_confirmed", "human_confirmed_inconsistent"):
        raise ConflictError("a confirmed document keeps its lines; correct a value instead")
    ln = s.get(InvoiceLineRow, line_id)
    if ln is None or ln.invoice_id != inv.id or ln.removed_at is not None:
        raise ValueError("no such line on this document")
    now = datetime.now(UTC)
    before = {f: _plain(getattr(ln, f)) for f in EDITABLE_LINE} | {"line_no": ln.line_no}
    ln.removed_at, ln.removed_by = now, user_id
    ln.removed_reason = (reason or "").strip() or None
    # The caller retires the line's current result (``exceptions.retire_line_result``): history only.
    inv.verification_status = "failed"
    inv.confirmed_by, inv.confirmed_at = None, None
    inv.review_draft = None
    doc = s.get(DocumentRow, inv.document_id)
    if doc is not None and doc.state == "succeeded":
        transition(s, "documents", doc.id, doc.state_version, "needs_review")
    inv.version += 1
    s.flush()
    gates = current_gates(s, inv)
    write_audit(
        s,
        inv.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="invoice.line_removed",
        entity_type="invoice",
        entity_id=inv.id,
        before=before,
        after={"line_no": ln.line_no, "reason": ln.removed_reason, "gates": gates},
    )
    return inv, gates
