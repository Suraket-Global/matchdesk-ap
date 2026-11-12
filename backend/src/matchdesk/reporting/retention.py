"""Archive export and account deletion requests (schema.md section 8; TRD 12; B9).

**Archive.** A controller asks for an archive; the worker writes one ZIP with a CSV per record type
of the account (documents index, invoices and lines, exceptions, receiving, reports and findings,
finding outcomes, the audit log) and the original files, read through ``blobstore`` inside the
tenant session. The ZIP is stored as a ``documents`` row with purpose ``export`` and removed 24 hours
after it is ready (schema.md 8, generated exports).

**Deletion.** A controller requests deletion of the account; the operator schedules it on S-18
(``delete_after`` = 30 days later, so approved reports, the audit log and the archive can be
exported first; reports and audit events are kept for the life of the account and deleted with it)
or declines it; the controller may cancel until it runs. When due, the worker deletes every stored
file, then the database function ``purge_tenant`` deletes every row of the account in dependency
order and writes ``deletion_ledger``. Each step before execution is in the account's audit log; the
ledger is the record that survives the account.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from matchdesk import blobstore
from matchdesk.audit import write_audit
from matchdesk.audit.models import AuditEvent
from matchdesk.core import ConflictError, ForbiddenError, get_correlation_id, get_logger, new_correlation_id
from matchdesk.exceptions.models import ExceptionRow
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.receiving.models import ReceiptLineRow, ReceivingImportRow
from matchdesk.reporting.models import (
    ArchiveExport,
    BacktestReport,
    DeletionRequest,
    FindingOutcomeRow,
    ReportFinding,
)
from matchdesk.tenancy import enqueue, global_session, operator_session, session

log = get_logger("matchdesk.reporting.retention")

ARCHIVE_TASK = "archive_export"
ARCHIVE_LIFETIME = timedelta(hours=24)  # schema.md 8: generated exports [assumption]
DELETION_NOTICE = timedelta(days=30)  # time to export before deletion [assumption]
ORIGINAL_PURPOSES = ("invoice", "receiving")
EXT = {"application/pdf": "pdf", "text/csv": "csv", "image/png": "png", "image/jpeg": "jpg"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ------------------------------------------------------------------------------ archive export


def request_archive(s: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> ArchiveExport:
    """Queue one archive (controller). A second request while one is being built returns that one."""
    running = s.scalar(select(ArchiveExport).where(ArchiveExport.status.in_(("queued", "running"))).limit(1))
    if running is not None:
        return running
    row = ArchiveExport(tenant_id=tenant_id, requested_by=user_id, status="queued")
    s.add(row)
    s.flush()
    enqueue(
        s, ARCHIVE_TASK, tenant_id, {"export_id": str(row.id)}, get_correlation_id() or new_correlation_id()
    )
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="archive.requested",
        entity_type="archive_export",
        entity_id=row.id,
    )
    return row


def _csv(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else str(r.get(k))) for k in columns})
    return buf.getvalue().encode()


def _plain(obj: Any, columns: list[str]) -> dict[str, Any]:
    return {c: getattr(obj, c) for c in columns}


TABLES: dict[str, tuple[type, list[str]]] = {
    "invoices.csv": (
        InvoiceRow,
        [
            "id",
            "document_id",
            "doc_type",
            "vendor_id",
            "doc_number",
            "doc_date",
            "po_number_read",
            "total",
            "tax_total",
            "currency",
            "verification_status",
            "inconsistent_note",
            "confirmed_at",
        ],
    ),
    "invoice_lines.csv": (
        InvoiceLineRow,
        [
            "id",
            "invoice_id",
            "line_no",
            "supplier_item_code",
            "description",
            "qty",
            "uom",
            "unit_price",
            "amount",
            "line_kind",
            "removed_at",
            "removed_reason",
        ],
    ),
    "exceptions.csv": (
        ExceptionRow,
        [
            "id",
            "invoice_id",
            "invoice_line_id",
            "type",
            "sub_reason",
            "status",
            "value_class",
            "variance_qty",
            "variance_amount",
            "reported_amount",
            "qualifying",
            "resolution_code",
            "resolution_note",
            "resolved_at",
            "credit_decision",
            "label",
        ],
    ),
    "receiving_imports.csv": (
        ReceivingImportRow,
        [
            "id",
            "document_id",
            "source_type",
            "evidence_class",
            "state",
            "declared_complete",
            "coverage_start",
            "coverage_end",
            "rows_total",
            "rows_valid",
            "rows_rejected",
            "committed_at",
            "voided_at",
            "void_reason",
        ],
    ),
    "receipt_lines.csv": (
        ReceiptLineRow,
        [
            "id",
            "receiving_import_id",
            "receipt_id",
            "po_line_id",
            "qty_received",
            "uom",
            "qty_in_po_uom",
            "source_row",
            "added_after_exception",
            "late_approved",
        ],
    ),
    "backtest_reports.csv": (
        BacktestReport,
        [
            "id",
            "period_start",
            "period_end",
            "version_no",
            "status",
            "data_cutoff_at",
            "approved_at",
            "findings_amount",
            "not_received_amount",
            "unverified_amount",
            "qualifying_amount",
            "receipt_coverage_pct",
        ],
    ),
    "report_findings.csv": (
        ReportFinding,
        [
            "id",
            "report_id",
            "exception_id",
            "section",
            "type",
            "vendor_id",
            "amount",
            "qualifying",
            "paid_status",
        ],
    ),
    "finding_outcomes.csv": (
        FindingOutcomeRow,
        [
            "id",
            "report_finding_id",
            "outcome",
            "amount",
            "recorded_by",
            "credit_reference",
            "note",
            "created_at",
        ],
    ),
    "audit_events.csv": (
        AuditEvent,
        [
            "occurred_at",
            "actor_type",
            "actor_user_id",
            "action",
            "entity_type",
            "entity_id",
            "before",
            "after",
        ],
    ),
}


def build_archive(
    s: Session, tenant_id: uuid.UUID, export_id: uuid.UUID, now: datetime | None = None
) -> ArchiveExport:
    """Write the ZIP for one queued export (worker; inside the tenant session)."""
    row = s.get(ArchiveExport, export_id)
    if row is None or row.status not in ("queued", "running"):
        raise ConflictError("this archive is not waiting to be built")
    at = now or datetime.now(UTC)
    row.status = "running"
    s.flush()
    buf = io.BytesIO()
    files = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        index: list[dict[str, Any]] = []
        for doc in s.scalars(
            select(DocumentRow)
            .where(DocumentRow.purpose.in_(ORIGINAL_PURPOSES), DocumentRow.deleted_at.is_(None))
            .order_by(DocumentRow.created_at, DocumentRow.id)
        ):
            ext = "xlsx" if doc.mime_type == XLSX else EXT.get(doc.mime_type, "bin")
            path = f"documents/{doc.id}.{ext}"
            try:
                z.writestr(path, blobstore.get(tenant_id, doc.blob_key))
                files += 1
            except Exception:  # a missing file is listed, not silently dropped
                path = ""
            index.append(
                {
                    "id": doc.id,
                    "purpose": doc.purpose,
                    "original_name": doc.original_name,
                    "mime_type": doc.mime_type,
                    "byte_size": doc.byte_size,
                    "uploaded_at": doc.created_at,
                    "state": doc.state,
                    "file_in_archive": path or "missing",
                }
            )
        z.writestr(
            "documents.csv",
            _csv(
                index,
                [
                    "id",
                    "purpose",
                    "original_name",
                    "mime_type",
                    "byte_size",
                    "uploaded_at",
                    "state",
                    "file_in_archive",
                ],
            ),
        )
        for name, (model, cols) in TABLES.items():
            found: list[Any] = list(s.scalars(select(model)).all())
            rows = [_plain(r, cols) for r in found]
            z.writestr(name, _csv(rows, cols))
        z.writestr(
            "README.txt",
            "MatchDesk archive of one account. documents.csv indexes the original files under documents/; "
            "each other CSV holds one kind of record. Amounts are exact decimals; dates are ISO 8601.\n",
        )
    data = buf.getvalue()
    doc_id = uuid.uuid4()
    key = blobstore.build_key(tenant_id, "export", data, source="system", record_id=doc_id, ext="zip")
    blobstore.put(tenant_id, key, data, content_type="application/zip")
    doc = DocumentRow(
        id=doc_id,
        tenant_id=tenant_id,
        purpose="export",
        source="system",
        blob_key=key,
        sha256=hashlib.sha256(data).digest(),
        mime_type="application/zip",
        byte_size=len(data),
        state="succeeded",
        correlation_id=uuid.UUID(get_correlation_id() or new_correlation_id()),
        original_name=f"matchdesk-archive-{at:%Y-%m-%d}.zip",
    )
    s.add(doc)
    s.flush()
    row.status, row.document_id = "ready", doc.id
    row.file_count, row.byte_size = files, len(data)
    row.finished_at, row.expires_at = at, at + ARCHIVE_LIFETIME
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="job",
        action="archive.ready",
        entity_type="archive_export",
        entity_id=row.id,
        after={"files": files, "bytes": len(data)},
    )
    return row


def make_archive_handler() -> Any:
    def handler(s: Session, payload: dict[str, Any]) -> None:
        build_archive(s, uuid.UUID(payload["tenant_id"]), uuid.UUID(payload["export_id"]))

    return handler


def expire_archives(engine: Engine, now: datetime | None = None) -> int:
    """Delete ready archives 24 hours after they were built (worker schedule)."""
    at = now or datetime.now(UTC)
    n = 0
    for tid in _tenant_ids(engine):
        with session(tid, engine) as s:
            for row in s.scalars(
                select(ArchiveExport).where(ArchiveExport.status == "ready", ArchiveExport.expires_at < at)
            ):
                doc = s.get(DocumentRow, row.document_id) if row.document_id else None
                if doc is not None and doc.deleted_at is None:
                    blobstore.delete(tid, doc.blob_key)
                    doc.deleted_at = at
                row.status = "expired"
                n += 1
    return n


def describe_archive(row: ArchiveExport, now: datetime | None = None) -> dict[str, Any]:
    at = now or datetime.now(UTC)
    ready = row.status == "ready" and row.expires_at is not None and row.expires_at > at
    return {
        "id": str(row.id),
        "status": row.status if row.status != "ready" or ready else "expired",
        "requested_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "file_count": row.file_count,
        "byte_size": row.byte_size,
        "downloadable": ready,
    }


# ------------------------------------------------------------------------------ account deletion


def open_deletion(s: Session) -> DeletionRequest | None:
    return s.scalar(select(DeletionRequest).where(DeletionRequest.status.in_(("requested", "scheduled"))))


def request_deletion(
    s: Session, tenant_id: uuid.UUID, user_id: uuid.UUID, reason: str | None
) -> DeletionRequest:
    found = open_deletion(s)
    if found is not None:
        raise ConflictError("a deletion request for this account is already open")
    row = DeletionRequest(
        tenant_id=tenant_id, scope="account", reason=(reason or "").strip() or None, requested_by=user_id
    )
    s.add(row)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="deletion.requested",
        entity_type="deletion_request",
        entity_id=row.id,
        after={"scope": "account", "reason": row.reason},
    )
    return row


def cancel_deletion(
    s: Session, row: DeletionRequest, user_id: uuid.UUID, expected_version: int
) -> DeletionRequest:
    if row.version != expected_version:
        raise ConflictError("stale version")
    if row.status not in ("requested", "scheduled"):
        raise ConflictError(f"a deletion request in status {row.status} cannot be cancelled")
    before = row.status
    row.status, row.cancelled_by, row.cancelled_at = "cancelled", user_id, datetime.now(UTC)
    row.version += 1
    s.flush()
    write_audit(
        s,
        row.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="deletion.cancelled",
        entity_type="deletion_request",
        entity_id=row.id,
        before={"status": before},
        after={"status": "cancelled"},
    )
    return row


def decide_deletion(
    s: Session,
    row: DeletionRequest,
    operator_id: uuid.UUID,
    decision: str,
    note: str | None,
    expected_version: int,
    now: datetime | None = None,
) -> tuple[DeletionRequest, dict[str, Any]]:
    """The operator schedules (30 days' notice) or declines a requested deletion (S-18). Runs in an
    operator session; the caller writes the account's audit event from the returned change."""
    if decision not in ("schedule", "decline"):
        raise ValueError("decision must be schedule or decline")
    if row.version != expected_version:
        raise ConflictError("stale version")
    if row.status != "requested":
        raise ConflictError(f"a deletion request in status {row.status} cannot be decided")
    at = now or datetime.now(UTC)
    row.status = "scheduled" if decision == "schedule" else "declined"
    row.decided_by, row.decided_at = operator_id, at
    row.decision_note = (note or "").strip() or None
    row.delete_after = at + DELETION_NOTICE if decision == "schedule" else None
    row.version += 1
    s.flush()
    return row, {
        "status": row.status,
        "delete_after": row.delete_after.isoformat() if row.delete_after else None,
        "note": row.decision_note,
    }


def describe_deletion(
    row: DeletionRequest | None, names: dict[uuid.UUID, str] | None = None
) -> dict[str, Any] | None:
    if row is None:
        return None
    n = names or {}
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "status": row.status,
        "reason": row.reason,
        "requested_by": str(row.requested_by),
        "requested_by_name": n.get(row.requested_by),
        "requested_at": row.created_at.isoformat(),
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_note": row.decision_note,
        "delete_after": row.delete_after.isoformat() if row.delete_after else None,
        "version": row.version,
    }


def operator_deletions(engine: Engine) -> list[DeletionRequest]:
    with operator_session(engine) as s:
        return list(s.scalars(select(DeletionRequest).order_by(DeletionRequest.created_at)).all())


def _tenant_ids(engine: Engine) -> list[uuid.UUID]:
    with global_session(engine) as g:
        return [r[0] for r in g.execute(text("select id from tenants order by id")).all()]


def execute_due_deletions(engine: Engine) -> list[uuid.UUID]:
    """Delete every account whose scheduled deletion is due (worker schedule). Files first through
    ``blobstore`` (each delete is idempotent, so a retry resumes), then ``purge_tenant`` removes the
    rows in one transaction and writes the ledger."""
    with operator_session(engine) as s:
        due = list(
            s.scalars(
                select(DeletionRequest.tenant_id).where(
                    DeletionRequest.status == "scheduled", DeletionRequest.delete_after <= datetime.now(UTC)
                )
            ).all()
        )
    done: list[uuid.UUID] = []
    for tid in due:
        with session(tid, engine) as s:
            keys = list(s.scalars(select(DocumentRow.blob_key)).all())
        for key in keys:
            blobstore.delete(tid, key)
        with global_session(engine) as g:
            rows = g.scalar(text("select purge_tenant(:t)"), {"t": str(tid)})
        log.info("account_deleted", extra={"rows": int(rows or 0)})
        done.append(tid)
    return done


def assert_controller(role: str) -> None:
    if role != "controller":
        raise ForbiddenError("only the controller requests an archive or the account's deletion")
