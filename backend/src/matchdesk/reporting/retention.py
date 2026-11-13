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

from sqlalchemy import Engine, and_, or_, select, text, update
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
    """Write the ZIP for one queued export (worker; inside the tenant session).

    B10: every original the account holds is expected. One that cannot be read is listed in
    ``documents.csv`` as missing and counted; the archive is then ``incomplete``, never ``ready``,
    and ``retry_archive`` builds it again. A rebuilt archive replaces the earlier ZIP."""
    row = s.get(ArchiveExport, export_id)
    if row is None or row.status not in ("queued", "running"):
        raise ConflictError("this archive is not waiting to be built")
    at = now or datetime.now(UTC)
    row.status = "running"
    s.flush()
    buf = io.BytesIO()
    expected = 0
    files = 0
    missing: list[str] = []
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        index: list[dict[str, Any]] = []
        for doc in s.scalars(
            select(DocumentRow)
            .where(DocumentRow.purpose.in_(ORIGINAL_PURPOSES), DocumentRow.deleted_at.is_(None))
            .order_by(DocumentRow.created_at, DocumentRow.id)
        ):
            expected += 1
            ext = "xlsx" if doc.mime_type == XLSX else EXT.get(doc.mime_type, "bin")
            path = f"documents/{doc.id}.{ext}"
            try:
                z.writestr(path, blobstore.get(tenant_id, doc.blob_key))
                files += 1
            except Exception:  # a missing file is listed and counted, never silently dropped
                log.warning("archive_original_unreadable", extra={"document_id": str(doc.id)})
                missing.append(str(doc.id))
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
        completeness = (
            f"Complete: {files} of {expected} original files are included.\n"
            if not missing
            else f"INCOMPLETE: {files} of {expected} original files are included; {len(missing)} could not be "
            "read and are marked missing in documents.csv. Retry the missing files on the Account data screen.\n"
        )
        z.writestr(
            "README.txt",
            "MatchDesk archive of one account. documents.csv indexes the original files under documents/; "
            "each other CSV holds one kind of record. Amounts are exact decimals; dates are ISO 8601.\n"
            + completeness,
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
    earlier = s.get(DocumentRow, row.document_id) if row.document_id else None
    if earlier is not None and earlier.deleted_at is None:  # a retry replaces the earlier ZIP
        blobstore.delete(tenant_id, earlier.blob_key)
        earlier.deleted_at = at
    row.status, row.document_id = ("incomplete" if missing else "ready"), doc.id
    row.file_count, row.byte_size = files, len(data)
    row.expected_count, row.included_count, row.missing_count = expected, files, len(missing)
    row.missing_document_ids = missing
    row.finished_at, row.expires_at = at, at + ARCHIVE_LIFETIME
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="job",
        action="archive.incomplete" if missing else "archive.ready",
        entity_type="archive_export",
        entity_id=row.id,
        after={"files": files, "expected": expected, "missing": len(missing), "bytes": len(data)},
    )
    open_req = open_deletion(s)
    if open_req is not None:  # the operator's row shows the latest verified archive
        _snapshot_archive(open_req, row, at)
        s.flush()
    return row


def retry_archive(s: Session, row: ArchiveExport, user_id: uuid.UUID) -> ArchiveExport:
    """Build an incomplete archive again, reading the missing originals once more (controller)."""
    if row.status != "incomplete":
        raise ConflictError("only an incomplete archive can be retried")
    row.status = "queued"
    s.flush()
    enqueue(
        s,
        ARCHIVE_TASK,
        row.tenant_id,
        {"export_id": str(row.id)},
        get_correlation_id() or new_correlation_id(),
    )
    write_audit(
        s,
        row.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="archive.retry_requested",
        entity_type="archive_export",
        entity_id=row.id,
        before={"missing": row.missing_count},
    )
    return row


def archive_state(row: ArchiveExport | None) -> str:
    """The verified state of an archive as the deletion screens show it."""
    if row is None or (row.status in ("queued", "running") and row.finished_at is None):
        return "none"
    if row.status == "failed":
        return "failed"
    return "incomplete" if (row.missing_count or 0) > 0 else "complete"


def latest_finished_archive(s: Session) -> ArchiveExport | None:
    return s.scalar(
        select(ArchiveExport)
        .where(ArchiveExport.status.in_(("ready", "incomplete", "failed", "expired")))
        .order_by(ArchiveExport.finished_at.desc().nulls_last(), ArchiveExport.created_at.desc())
        .limit(1)
    )


def describe_archive_state(row: ArchiveExport | None) -> dict[str, Any]:
    return {
        "state": archive_state(row),
        "included": row.included_count if row is not None else None,
        "expected": row.expected_count if row is not None else None,
        "checked_at": row.finished_at.isoformat() if row is not None and row.finished_at else None,
    }


def _snapshot_archive(req: DeletionRequest, row: ArchiveExport | None, at: datetime) -> None:
    req.archive_state = archive_state(row)
    req.archive_included = row.included_count if row is not None else None
    req.archive_expected = row.expected_count if row is not None else None
    req.archive_checked_at = (row.finished_at if row is not None else None) or at


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
                select(ArchiveExport).where(
                    ArchiveExport.status.in_(("ready", "incomplete")), ArchiveExport.expires_at < at
                )
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
    built = row.status in ("ready", "incomplete")
    ready = built and row.expires_at is not None and row.expires_at > at
    return {
        "id": str(row.id),
        "status": row.status if not built or ready else "expired",
        "complete": built and (row.missing_count or 0) == 0,
        "expected_count": row.expected_count,
        "included_count": row.included_count,
        "missing_count": row.missing_count,
        "requested_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "file_count": row.file_count,
        "byte_size": row.byte_size,
        "downloadable": ready,
    }


# ------------------------------------------------------------------------------ account deletion


OPEN_DELETION = ("requested", "scheduled", "deleting")
CANCELLABLE = ("requested", "scheduled")
RESUME_AFTER = timedelta(minutes=15)  # a claim older than this is taken over by the next run [assumption]


class ArchiveNotComplete(ConflictError):
    """Deletion asked without a complete archive and without the controller's acknowledgement."""


def open_deletion(s: Session) -> DeletionRequest | None:
    return s.scalar(select(DeletionRequest).where(DeletionRequest.status.in_(OPEN_DELETION)))


def request_deletion(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str | None,
    acknowledge_incomplete_archive: bool = False,
) -> DeletionRequest:
    """Record the controller's request. Decision (B10, outside QA item 1): deletion may proceed
    without a complete archive, but only when the controller explicitly acknowledges it; the
    acknowledgement and the archive state at that moment are stored and shown to the operator."""
    found = open_deletion(s)
    if found is not None:
        raise ConflictError("a deletion request for this account is already open")
    latest = latest_finished_archive(s)
    state = archive_state(latest)
    if state != "complete" and not acknowledge_incomplete_archive:
        words = {
            "none": "No archive of this account has been prepared",
            "failed": "The last archive could not be built",
            "incomplete": (
                f"The latest archive is incomplete ({latest.included_count} of {latest.expected_count} originals)"
                if latest is not None
                else "The latest archive is incomplete"
            ),
        }[state]
        raise ArchiveNotComplete(
            f"{words}. Prepare a complete archive first, or acknowledge that the account is deleted without one."
        )
    row = DeletionRequest(
        tenant_id=tenant_id,
        scope="account",
        reason=(reason or "").strip() or None,
        requested_by=user_id,
        archive_acknowledged=state != "complete",
    )
    _snapshot_archive(row, latest, datetime.now(UTC))
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
        after={
            "scope": "account",
            "reason": row.reason,
            "archive": state,
            "archive_acknowledged": row.archive_acknowledged,
        },
    )
    return row


def cancel_deletion(
    s: Session, row: DeletionRequest, user_id: uuid.UUID, expected_version: int
) -> DeletionRequest:
    """Cancel while the files are still protected. B10 (outside QA item 2): one conditional UPDATE,
    so a cancellation read before the worker's claim cannot win after it: once the worker has
    claimed the deletion (``deleting``) the update matches no row and the request is refused."""
    if row.version != expected_version:
        raise ConflictError("stale version")
    before = row.status
    at = datetime.now(UTC)
    changed = s.execute(
        update(DeletionRequest)
        .where(
            DeletionRequest.id == row.id,
            DeletionRequest.version == expected_version,
            DeletionRequest.status.in_(CANCELLABLE),
        )
        .values(
            status="cancelled", cancelled_by=user_id, cancelled_at=at, version=DeletionRequest.version + 1
        )
        .returning(DeletionRequest.id)
        .execution_options(synchronize_session=False)
    ).first()
    s.refresh(row)
    if changed is None:
        if row.status == "deleting":
            raise ConflictError(
                "the deletion is already running: files are being removed, so it can no longer be cancelled"
            )
        if row.status in CANCELLABLE:
            raise ConflictError("stale version")
        raise ConflictError(f"a deletion request in status {row.status} cannot be cancelled")
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
        "claimed_at": row.claimed_at.isoformat() if row.claimed_at else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "cancellable": row.status in CANCELLABLE,
        "archive": {
            "state": row.archive_state or "none",
            "included": row.archive_included,
            "expected": row.archive_expected,
            "checked_at": row.archive_checked_at.isoformat() if row.archive_checked_at else None,
            "acknowledged": row.archive_acknowledged,
        },
        "version": row.version,
    }


def operator_deletions(engine: Engine) -> list[DeletionRequest]:
    with operator_session(engine) as s:
        return list(s.scalars(select(DeletionRequest).order_by(DeletionRequest.created_at)).all())


def _tenant_ids(engine: Engine) -> list[uuid.UUID]:
    with global_session(engine) as g:
        return [r[0] for r in g.execute(text("select id from tenants order by id")).all()]


def claim_due_deletions(engine: Engine, now: datetime | None = None) -> list[uuid.UUID]:
    """Claim every due deletion (status ``deleting``) with one conditional UPDATE per account, inside
    that account's session and committed before any file is removed. The operator session only
    finds the candidates. A claim left by a worker that stopped is taken over after ``RESUME_AFTER``."""
    at = now or datetime.now(UTC)
    due = or_(
        and_(DeletionRequest.status == "scheduled", DeletionRequest.delete_after <= at),
        and_(DeletionRequest.status == "deleting", DeletionRequest.claimed_at < at - RESUME_AFTER),
    )
    with operator_session(engine) as s:
        candidates = list(s.scalars(select(DeletionRequest.tenant_id).where(due)).all())
    claimed: list[uuid.UUID] = []
    for tid in candidates:
        with session(tid, engine) as s:
            got = s.execute(
                update(DeletionRequest)
                .where(due)
                .values(status="deleting", claimed_at=at, version=DeletionRequest.version + 1)
                .returning(DeletionRequest.id)
                .execution_options(synchronize_session=False)
            ).first()
            if got is None:  # cancelled (or claimed by another worker) since the candidates were read
                continue
            write_audit(
                s,
                tid,
                actor_type="job",
                action="deletion.started",
                entity_type="deletion_request",
                entity_id=got[0],
                after={"status": "deleting"},
            )
        claimed.append(tid)
    return claimed


def execute_due_deletions(engine: Engine) -> list[uuid.UUID]:
    """Delete every account whose scheduled deletion is due (worker schedule). The deletion is
    claimed first (``claim_due_deletions``), so a cancellation after this point is refused; then the
    files through ``blobstore`` (each delete is idempotent, so a retry resumes), then
    ``purge_tenant`` removes the rows in one transaction and writes the ledger."""
    done: list[uuid.UUID] = []
    for tid in claim_due_deletions(engine):
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
