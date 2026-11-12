"""Receiving imports (T-3.2.1 (a) to (f); T-3.2.2 class B confirmation; MH-03, MH-07).

Upload with an evidence class, coverage declaration, column mapping, validation, commit, void.
Validation never rejects a row for its date: receipts of any date count (no date-window rule,
CLAUDE.md prohibited shortcuts). QuickBooks item-receipt export rows pass the independence rule
``item_receipt_rejection`` or become rejected rows with the reason (C1). Class C rows are stored as
context and never count; class B lines count only after a person records the receiver's marks and
name for the delivery document (``confirm_receipt``). Whether a line counts is decided by
``matching.receipt_line_counts`` from these facts, never stored as a shortcut here.

``receiving`` does not import ``exceptions``: the caller passes the PO lines that had an open
exception at commit time (late evidence, IT-28) and requests the re-match.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk import blobstore
from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, NotFoundError, get_correlation_id, new_correlation_id
from matchdesk.matching import normalise_code, normalise_number, normalise_uom
from matchdesk.qbo.models import Item, PoLineRow, PurchaseOrderRow
from matchdesk.receiving.models import (
    ReceiptLineRow,
    ReceiptRow,
    ReceivingAttestation,
    ReceivingImportRow,
    ReceivingMapping,
)
from matchdesk.receiving.parse import CSV_TYPE, ReceivingFileError, read_table, sniff_receiving
from matchdesk.receiving.qbo_item_receipts import SOURCE_TYPE as QBO_EXPORT
from matchdesk.receiving.qbo_item_receipts import QboItemReceiptRow, item_receipt_rejection
from matchdesk.tenancy import lock_for_update, transition

TARGETS = (
    "po_number",
    "line_no",
    "item_code",
    "qty_received",
    "uom",
    "received_date",
    "receiver_ref",
    "created_by",
    "created_at",
    "linked_bill_created_by",
    "linked_bill_created_at",
)
REQUIRED = ("po_number", "qty_received", "received_date")
DRAFT_LIFETIME = timedelta(days=7)
LIVE = ("queued", "running", "succeeded")


@dataclass
class ValidatedRow:
    row: int
    po_id: uuid.UUID
    po_line_id: uuid.UUID
    qty: Decimal
    uom: str | None
    received_date: date
    receiver_ref: str | None


@dataclass
class Validation:
    total: int = 0
    valid: list[ValidatedRow] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)


def create_import(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: bytes,
    source_type: str,
    evidence_class: str,
    kept_by_name: str | None = None,
    original_name: str | None = None,
) -> tuple[ReceivingImportRow, dict[str, Any]]:
    """Store the file and a draft import; return it with a preview (headers, first rows). The
    user-supplied file name is kept in the database only, never in a key or a log (TRD 8.7)."""
    mime = sniff_receiving(data)
    if mime is None:
        raise ReceivingFileError("only CSV and XLSX receiving files are accepted")
    if source_type == QBO_EXPORT and evidence_class != "A":
        raise ReceivingFileError("a QuickBooks item-receipt export is always class A")
    header, rows = read_table(data, mime)
    sha = hashlib.sha256(data).digest()
    if s.scalar(
        select(ReceivingImportRow.id).where(
            ReceivingImportRow.file_sha256 == sha, ReceivingImportRow.state.in_(LIVE)
        )
    ):
        raise ConflictError("this receiving file was already imported")
    from matchdesk.intake.models import DocumentRow  # the documents table is shared (schema.md 3.4)

    corr = get_correlation_id() or new_correlation_id()
    doc_id = uuid.uuid4()
    ext = "csv" if mime == CSV_TYPE else "xlsx"
    key = blobstore.build_key(tenant_id, "receiving", data, source="upload", record_id=doc_id, ext=ext)
    blobstore.put(tenant_id, key, data, content_type=mime)
    doc = DocumentRow(
        id=doc_id,
        tenant_id=tenant_id,
        purpose="receiving",
        source="upload",
        blob_key=key,
        sha256=sha,
        mime_type=mime,
        byte_size=len(data),
        state="succeeded",
        correlation_id=uuid.UUID(corr),
        original_name=(original_name or "")[:255] or None,
    )
    s.add(doc)
    s.flush()
    imp = ReceivingImportRow(
        tenant_id=tenant_id,
        source_type=source_type,
        evidence_class=evidence_class,
        document_id=doc.id,
        file_sha256=sha,
        state="draft",
        state_version=0,
        kept_by_name=kept_by_name,
        rows_total=len(rows),
        created_by=user_id,
        expires_at=datetime.now(UTC) + DRAFT_LIFETIME,
    )
    s.add(imp)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.uploaded",
        entity_type="receiving_import",
        entity_id=imp.id,
        after={"source_type": source_type, "evidence_class": evidence_class, "rows": len(rows)},
    )
    return imp, {"headers": header, "sample_rows": rows[:PREVIEW_ROWS], "rows_total": len(rows)}


PREVIEW_ROWS = 20  # S-05: "preview first 20 rows"


def file_preview(s: Session, imp: ReceivingImportRow) -> dict[str, Any]:
    """Headers and the first rows of a stored receiving file, for the mapping step (B4, S-05)."""
    from matchdesk.intake.models import DocumentRow  # the documents table is shared (schema.md 3.4)

    doc = s.get(DocumentRow, imp.document_id)
    if doc is None:
        return {"headers": [], "sample_rows": [], "rows_total": 0}
    header, rows = read_table(blobstore.get(imp.tenant_id, doc.blob_key), doc.mime_type)
    return {"headers": header, "sample_rows": rows[:PREVIEW_ROWS], "rows_total": len(rows)}


def set_declaration(
    s: Session,
    imp: ReceivingImportRow,
    user_id: uuid.UUID,
    declared_complete: bool,
    coverage_start: date | None,
    coverage_end: date | None,
    kept_by_name: str | None,
) -> ReceivingImportRow:
    """Class A only: the range for which the log is complete and who keeps it (TRD 8.5 coverage)."""
    if imp.state == "voided":
        raise ConflictError("a voided import cannot be changed")
    if declared_complete and imp.evidence_class != "A":
        raise ConflictError("only a class A warehouse log can be declared complete")
    if declared_complete and (
        coverage_start is None or coverage_end is None or coverage_end < coverage_start
    ):
        raise ValueError("a complete declaration needs a start and an end date")
    before = {"declared_complete": imp.declared_complete}
    imp.declared_complete = declared_complete
    imp.coverage_start = coverage_start if declared_complete else None
    imp.coverage_end = coverage_end if declared_complete else None
    if kept_by_name is not None:
        imp.kept_by_name = kept_by_name
    s.flush()
    write_audit(
        s,
        imp.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.declared",
        entity_type="receiving_import",
        entity_id=imp.id,
        before=before,
        after={
            "declared_complete": declared_complete,
            "coverage": [str(imp.coverage_start), str(imp.coverage_end)],
        },
    )
    return imp


def save_mapping(
    s: Session, imp: ReceivingImportRow, user_id: uuid.UUID, columns: dict[str, str], name: str | None = None
) -> ReceivingImportRow:
    unknown = set(columns) - set(TARGETS)
    if unknown:
        raise ValueError("unknown target fields: " + ", ".join(sorted(unknown)))
    missing = [t for t in REQUIRED if t not in columns]
    if "line_no" not in columns and "item_code" not in columns:
        missing.append("line_no or item_code")
    if missing:
        raise ValueError("mapping needs: " + ", ".join(missing))
    if imp.state != "draft":
        raise ConflictError("the mapping of a committed import cannot change")
    imp.column_map = dict(columns)
    if name:
        mapping = s.scalar(select(ReceivingMapping).where(ReceivingMapping.name == name))
        if mapping is None:
            mapping = ReceivingMapping(
                tenant_id=imp.tenant_id, name=name, columns=dict(columns), created_by=user_id
            )
            s.add(mapping)
        else:
            mapping.columns = dict(columns)
        s.flush()
        imp.mapping_id = mapping.id
    s.flush()
    return imp


def latest_attestation(s: Session) -> ReceivingAttestation | None:
    return s.scalar(
        select(ReceivingAttestation)
        .order_by(ReceivingAttestation.created_at.desc(), ReceivingAttestation.id.desc())
        .limit(1)
    )


def latest_ap_staff(s: Session) -> frozenset[str]:
    row = latest_attestation(s)
    return frozenset(str(n) for n in (row.ap_staff if row else []))


def attest(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    evidence_class: str,
    source: str,
    ap_staff: list[str],
) -> ReceivingAttestation:
    row = ReceivingAttestation(
        tenant_id=tenant_id,
        evidence_class=evidence_class,
        source_description=source,
        ap_staff=sorted({n.strip() for n in ap_staff if n.strip()}),
        attested_by=user_id,
    )
    s.add(row)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.attested",
        entity_type="receiving_attestation",
        entity_id=row.id,
        after={"evidence_class": evidence_class, "ap_staff_count": len(row.ap_staff)},
    )
    return row


def _date(value: str) -> date | None:
    v = value.strip()
    if v.isdigit() and 20000 <= int(v) <= 80000:  # an Excel serial day number
        return date(1899, 12, 30) + timedelta(days=int(v))
    for candidate in (v[:10], v[:10].replace("/", "-")):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _datetime(value: str) -> datetime | None:
    v = value.strip()
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def validate(s: Session, imp: ReceivingImportRow) -> Validation:
    """Map and check every row; nothing is written. No row is ever rejected for its date."""
    if not imp.column_map:
        raise ConflictError("save a column mapping first")
    from matchdesk.intake.models import DocumentRow

    doc = s.get(DocumentRow, imp.document_id)
    assert doc is not None
    header, rows = read_table(blobstore.get(imp.tenant_id, doc.blob_key), doc.mime_type)
    pos_by_number: dict[str, list[PurchaseOrderRow]] = defaultdict(list)
    for po in s.scalars(select(PurchaseOrderRow)):
        pos_by_number[po.po_number_norm].append(po)
    lines_by_po: dict[uuid.UUID, list[PoLineRow]] = defaultdict(list)
    for pl in s.scalars(select(PoLineRow)):
        lines_by_po[pl.purchase_order_id].append(pl)
    item_codes: dict[uuid.UUID, set[str]] = {
        it.id: {normalise_code(it.sku), normalise_code(it.name)} - {""} for it in s.scalars(select(Item))
    }
    ap_staff = latest_ap_staff(s) if imp.source_type == QBO_EXPORT else frozenset()
    col = {target: header.index(src) for target, src in imp.column_map.items() if src in header}
    out = Validation(total=len(rows))

    def cell(row: list[str], target: str) -> str:
        i = col.get(target)
        return row[i].strip() if i is not None and i < len(row) else ""

    for n, row in enumerate(rows, start=2):  # row 1 is the header

        def reject(reason: str, value: str = "") -> None:
            out.rejected.append({"row": n, "reason": reason, "value": value[:60]})  # noqa: B023

        po_ref = cell(row, "po_number")
        candidates = pos_by_number.get(normalise_number(po_ref), [])
        if not po_ref or not candidates:
            reject("po_not_found", po_ref)
            continue
        if len(candidates) > 1:
            reject("po_ambiguous", po_ref)
            continue
        po = candidates[0]
        line_no, code = cell(row, "line_no"), cell(row, "item_code")
        po_lines = [pl for pl in lines_by_po[po.id] if pl.charge_kind is None]
        if line_no:
            matches = [pl for pl in po_lines if str(pl.line_no) == line_no.split(".")[0]]
        else:
            norm = normalise_code(code)
            matches = [
                pl for pl in po_lines if pl.item_id and norm and norm in item_codes.get(pl.item_id, set())
            ]
        if not matches:
            reject("po_line_not_found", line_no or code)
            continue
        if len(matches) > 1:
            reject("po_line_ambiguous", line_no or code)
            continue
        pl = matches[0]
        raw_qty = cell(row, "qty_received")
        try:
            qty = Decimal(raw_qty.replace(",", ""))
        except InvalidOperation:
            reject("qty_unreadable", raw_qty)
            continue
        if qty == 0:
            reject("qty_zero", raw_qty)
            continue
        uom = cell(row, "uom") or None
        if uom and pl.uom and normalise_uom(uom) != normalise_uom(pl.uom):
            reject("uom_differs_from_po", uom)  # never converted silently (MH-10)
            continue
        raw_date = cell(row, "received_date")
        received = _date(raw_date)
        if received is None:
            reject("date_unreadable", raw_date)
            continue
        if imp.source_type == QBO_EXPORT:
            why = item_receipt_rejection(
                QboItemReceiptRow(
                    po_number=po.po_number,
                    created_by=cell(row, "created_by") or None,
                    created_at=_datetime(cell(row, "created_at")),
                    linked_bill_created_by=cell(row, "linked_bill_created_by") or None,
                    linked_bill_created_at=_datetime(cell(row, "linked_bill_created_at")),
                ),
                ap_staff,
            )
            if why is not None:
                reject(why.value)
                continue
        out.valid.append(ValidatedRow(n, po.id, pl.id, qty, uom, received, cell(row, "receiver_ref") or None))
    return out


def preview(s: Session, imp: ReceivingImportRow) -> dict[str, Any]:
    v = validate(s, imp)
    imp.rows_total, imp.rows_valid, imp.rows_rejected = v.total, len(v.valid), len(v.rejected)
    imp.rejected_rows = v.rejected
    s.flush()
    return {
        "rows_total": v.total,
        "rows_valid": len(v.valid),
        "rows_rejected": len(v.rejected),
        "rejected_rows": v.rejected,
    }


def commit(
    s: Session, imp: ReceivingImportRow, user_id: uuid.UUID, open_exception_po_lines: frozenset[uuid.UUID]
) -> tuple[ReceivingImportRow, list[uuid.UUID]]:
    """Import the valid rows once. Idempotent: committing a committed import changes nothing.
    Returns the import and the PO lines whose inputs changed (for the re-match)."""
    if imp.state == "succeeded":
        return imp, []
    if imp.state != "draft":
        raise ConflictError(f"an import in state {imp.state} cannot be committed")
    other = s.scalar(
        select(ReceivingImportRow.id).where(
            ReceivingImportRow.file_sha256 == imp.file_sha256,
            ReceivingImportRow.state.in_(LIVE),
            ReceivingImportRow.id != imp.id,
        )
    )
    if other is not None:
        raise ConflictError("this receiving file was already imported")
    if imp.source_type == QBO_EXPORT and latest_attestation(s) is None:
        # Without the attestation nobody has named the accounts-payable users, so no row can be
        # shown to be independent (B3/B4 review C1).
        raise ConflictError(
            "the controller must attest the receiving evidence and name the accounts-payable users "
            "before a QuickBooks item-receipt export is committed"
        )
    v = validate(s, imp)
    receipts: dict[tuple[uuid.UUID, date, str | None], ReceiptRow] = {}
    touched: set[uuid.UUID] = set()
    late = 0
    for r in v.valid:
        k = (r.po_id, r.received_date, r.receiver_ref)
        receipt = receipts.get(k)
        if receipt is None:
            receipt = ReceiptRow(
                tenant_id=imp.tenant_id,
                receiving_import_id=imp.id,
                purchase_order_id=r.po_id,
                received_date=r.received_date,
                receiver_ref=r.receiver_ref,
                version=1,
            )
            s.add(receipt)
            s.flush()
            receipts[k] = receipt
        is_late = r.po_line_id in open_exception_po_lines
        late += int(is_late)
        s.add(
            ReceiptLineRow(
                tenant_id=imp.tenant_id,
                receipt_id=receipt.id,
                receiving_import_id=imp.id,
                po_line_id=r.po_line_id,
                qty_received=r.qty,
                uom=r.uom,
                qty_in_po_uom=r.qty,
                source_row=r.row,
                added_after_exception=is_late,
                late_approved=False,
            )
        )
        touched.add(r.po_line_id)
    now = datetime.now(UTC)
    imp.rows_total, imp.rows_valid, imp.rows_rejected = v.total, len(v.valid), len(v.rejected)
    imp.rejected_rows = v.rejected
    imp.committed_by = user_id
    imp.expires_at = None
    s.flush()
    if not transition(s, "receiving_imports", imp.id, imp.state_version, "succeeded", committed_at=now):
        raise ConflictError("the import changed while it was being committed")
    s.refresh(imp)
    write_audit(
        s,
        imp.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.committed",
        entity_type="receiving_import",
        entity_id=imp.id,
        after={"lines": len(v.valid), "rejected": len(v.rejected), "late_lines": late},
    )
    return imp, sorted(touched)


def void(s: Session, imp: ReceivingImportRow, user_id: uuid.UUID, reason: str) -> list[uuid.UUID]:
    """Stop an import's lines counting (they stay stored); reason required. Returns affected PO lines."""
    if not reason.strip():
        raise ValueError("a reason is required")
    if imp.state == "voided":
        return []
    if imp.state != "succeeded":
        raise ConflictError("only a committed import can be voided")
    imp.voided_by, imp.void_reason = user_id, reason.strip()
    s.flush()
    if not transition(
        s, "receiving_imports", imp.id, imp.state_version, "voided", voided_at=datetime.now(UTC)
    ):
        raise ConflictError("the import changed while it was being voided")
    s.refresh(imp)
    write_audit(
        s,
        imp.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.voided",
        entity_type="receiving_import",
        entity_id=imp.id,
        after={"reason": imp.void_reason},
    )
    return affected_po_lines(s, imp.id)


def affected_po_lines(s: Session, import_id: uuid.UUID) -> list[uuid.UUID]:
    return sorted(
        set(
            s.scalars(
                select(ReceiptLineRow.po_line_id).where(ReceiptLineRow.receiving_import_id == import_id)
            ).all()
        )
    )


def late_line_count(s: Session, import_id: uuid.UUID) -> int:
    return len(
        s.scalars(
            select(ReceiptLineRow.id).where(
                ReceiptLineRow.receiving_import_id == import_id,
                ReceiptLineRow.added_after_exception.is_(True),
                ReceiptLineRow.late_approved.is_(False),
            )
        ).all()
    )


def approve_late_lines(s: Session, import_id: uuid.UUID) -> list[uuid.UUID]:
    """Called by the approval decision (controller): the import's late lines may now count."""
    rows = s.scalars(
        select(ReceiptLineRow).where(
            ReceiptLineRow.receiving_import_id == import_id, ReceiptLineRow.added_after_exception.is_(True)
        )
    ).all()
    for r in rows:
        r.late_approved = True
    s.flush()
    return sorted({r.po_line_id for r in rows})


def confirm_receipt(
    s: Session,
    receipt_id: uuid.UUID,
    user_id: uuid.UUID,
    expected_version: int,
    receiver_marks_present: bool,
    receiver_name: str | None,
) -> ReceiptRow:
    """Class B: record that the delivery document carries the receiver's marks and who signed.
    Its lines count only when both are recorded (UT-30)."""
    receipt = s.get(ReceiptRow, receipt_id)
    if receipt is None:
        raise NotFoundError("receipt")
    imp = s.get(ReceivingImportRow, receipt.receiving_import_id)
    assert imp is not None
    if imp.evidence_class != "B":
        raise ConflictError("only a class B delivery document is confirmed this way")
    lock_for_update(s, receipt)  # B3/B4 review M3
    if receipt.version != expected_version:
        raise ConflictError("stale version")
    receipt.receiver_marks_present = receiver_marks_present
    receipt.receiver_name = (receiver_name or "").strip() or None
    receipt.confirmed_by, receipt.confirmed_at = user_id, datetime.now(UTC)
    receipt.version += 1
    s.flush()
    write_audit(
        s,
        imp.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="receiving.receipt_confirmed",
        entity_type="receipt",
        entity_id=receipt.id,
        after={"marks": receiver_marks_present, "signer_recorded": receipt.receiver_name is not None},
    )
    return receipt


def describe_import(imp: ReceivingImportRow) -> dict[str, Any]:
    return {
        "id": str(imp.id),
        "source_type": imp.source_type,
        "evidence_class": imp.evidence_class,
        "state": imp.state,
        "state_version": imp.state_version,
        "kept_by_name": imp.kept_by_name,
        "declared_complete": imp.declared_complete,
        "coverage_start": imp.coverage_start.isoformat() if imp.coverage_start else None,
        "coverage_end": imp.coverage_end.isoformat() if imp.coverage_end else None,
        "column_map": imp.column_map,
        "rows_total": imp.rows_total,
        "rows_valid": imp.rows_valid,
        "rows_rejected": imp.rows_rejected,
        "rejected_rows": imp.rejected_rows or [],
        "committed_at": imp.committed_at.isoformat() if imp.committed_at else None,
        "voided_at": imp.voided_at.isoformat() if imp.voided_at else None,
        "void_reason": imp.void_reason,
        "counts_as_evidence": imp.evidence_class in ("A", "B"),
    }
