"""Store a match result: supersede, never overwrite (T-4.1.6 (c), (d); TRD 6.3; R-01).

In one transaction: previous current ``line_matches`` of the evaluated lines are
marked superseded and kept; new results are inserted; exceptions are reconciled
by fingerprint (kept and moved to the new result, reopened when the variance
changed, auto-closed when no longer produced), each change with an event.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.exceptions.models import Approval, ExceptionEvent, ExceptionRow, LineMatch, MatchRun
from matchdesk.matching import ExceptionResult, ExceptionStatus, LineStatus, MatchResult

PERSON_RESOLUTIONS = frozenset({"resolved", "waived", "pending_approval"})


def exception_fingerprint(document_id: str, line_id: str | None, typ: str) -> bytes:
    return hashlib.sha256(f"{document_id}|{line_id or ''}|{typ}".encode()).digest()


def _u(v: str | None) -> uuid.UUID | None:
    return uuid.UUID(v) if v else None


def store_result(s: Session, tenant_id: uuid.UUID, run: MatchRun, result: MatchResult) -> None:
    now = datetime.now(UTC)
    line_ids = [uuid.UUID(lr.line_id) for lr in result.lines]
    new_ids: dict[str, uuid.UUID] = {}
    if line_ids:
        s.execute(
            update(LineMatch)
            .where(LineMatch.invoice_line_id.in_(line_ids), LineMatch.is_current.is_(True))
            .values(is_current=False, superseded_by_run_id=run.id)
        )
    for lr in result.lines:
        lm = LineMatch(
            tenant_id=tenant_id,
            match_run_id=run.id,
            invoice_line_id=uuid.UUID(lr.line_id),
            line_kind=lr.line_kind.value,
            po_line_id=_u(lr.po_line_id),
            alias_id=_u(lr.alias_id),
            tolerance_rule_id=_u(lr.tolerance_rule_id),
            status=lr.status.value,
            qty_ordered=lr.qty_ordered,
            qty_received_cum=lr.qty_received_cum,
            qty_invoiced_cum_net=lr.qty_invoiced_cum_net,
            qty_invoiced_prior_qbo=lr.qty_invoiced_prior_qbo,
            receipt_line_count=lr.receipt_line_count,
            checks_run=list(lr.checks_run),
            covered=lr.covered,
            po_unit_price=lr.po_unit_price,
            invoice_unit_price_po_uom=lr.invoice_unit_price_po_uom,
        )
        s.add(lm)
        s.flush()
        new_ids[lr.line_id] = lm.id

    doc_ids = sorted(
        {uuid.UUID(lr.document_id) for lr in result.lines}
        | {uuid.UUID(e.document_id) for e in result.exceptions}
    )
    existing = {
        e.fingerprint: e
        for e in s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id.in_(doc_ids))).all()
    }
    produced: set[bytes] = set()
    raised = 0
    for er in result.exceptions:
        fp = exception_fingerprint(er.document_id, er.line_id, er.type.value)
        produced.add(fp)
        line_match_id = new_ids.get(er.line_id) if er.line_id else None
        row = existing.get(fp)
        if row is None:
            raised += 1
            row = ExceptionRow(
                tenant_id=tenant_id,
                fingerprint=fp,
                invoice_id=uuid.UUID(er.document_id),
                invoice_line_id=_u(er.line_id),
            )
            _apply(row, er, line_match_id)
            s.add(row)
            s.flush()
            _event(s, tenant_id, row, run, "raised", None, row.status)
            continue
        before_status = row.status
        variance_changed = row.variance_amount != er.variance_amount
        person_resolved = row.status in PERSON_RESOLUTIONS and row.resolution_code != "resolved_by_credit"
        if person_resolved and not variance_changed and er.status == ExceptionStatus.OPEN:
            row.line_match_id = line_match_id  # the clerk's work survives a re-match
            row.reported_amount = er.reported_amount
            row.qualifying = er.qualifying
        else:
            _apply(row, er, line_match_id)
            if person_resolved and variance_changed:
                row.status, row.resolution_code = "open", None
                _event(s, tenant_id, row, run, "reopened", before_status, "open")
            elif before_status == "auto_closed" and row.status == "open":
                _event(s, tenant_id, row, run, "reopened", before_status, "open")
            elif before_status != row.status:
                _event(s, tenant_id, row, run, "resolved", before_status, row.status)
        _withdraw_stale_approval(s, tenant_id, row, run, before_status)
        row.version += 1
    for fp, row in existing.items():
        if fp not in produced and row.status != "auto_closed":
            before = row.status
            row.status = "auto_closed"
            row.line_match_id = None
            row.version += 1
            _event(s, tenant_id, row, run, "auto_closed", before, "auto_closed")
            _withdraw_stale_approval(s, tenant_id, row, run, before)

    run.lines_evaluated = len(result.lines)
    run.lines_matched = sum(1 for lr in result.lines if lr.status == LineStatus.MATCHED)
    run.exceptions_raised = raised
    run.finished_at = now
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="job",
        action="match_run.stored",
        entity_type="match_run",
        entity_id=run.id,
        after={"lines": run.lines_evaluated, "matched": run.lines_matched},
    )


def _withdraw_stale_approval(
    s: Session, tenant_id: uuid.UUID, row: ExceptionRow, run: MatchRun, before_status: str
) -> None:
    """A waiver waiting for approval was requested for one status and amount. When a re-match moves
    the exception out of ``pending_approval`` or changes the amount, the pending approval is withdrawn
    and the exception is open again, so the controller never applies a waiver to an exception that
    changed (B3/B4 review M1)."""
    if before_status != "pending_approval":
        return
    approval = s.scalar(
        select(Approval).where(
            Approval.exception_id == row.id, Approval.subject_type == "waiver", Approval.status == "pending"
        )
    )
    if approval is None:
        return
    amount = row.reported_amount if row.reported_amount is not None else row.variance_amount
    if row.status == "pending_approval" and amount == approval.amount:
        return
    approval.status, approval.version = "withdrawn", approval.version + 1
    if row.status == "pending_approval":
        row.status = "open"
        _event(s, tenant_id, row, run, "reopened", "pending_approval", "open")
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="job",
        action="approval.withdrawn_by_rematch",
        entity_type="approval",
        entity_id=approval.id,
        after={"exception_id": str(row.id), "status": row.status, "match_run_id": str(run.id)},
    )


def _apply(row: ExceptionRow, er: ExceptionResult, line_match_id: uuid.UUID | None) -> None:
    row.line_match_id = line_match_id
    row.type = er.type.value
    row.sub_reason = er.sub_reason.value if er.sub_reason else None
    row.possibly_credited_bill_id = _u(er.possibly_credited_bill_id)
    row.variance_qty = er.variance_qty
    row.variance_amount = er.variance_amount
    row.reported_amount = er.reported_amount
    row.value_class = er.value_class.value
    row.qualifying = er.qualifying
    row.related_invoice_id = None
    if er.related_document_id:
        # Only an uploaded document can be referenced; QuickBooks credits are named in the label.
        row.related_invoice_id = _u(er.related_document_id) if er.label is None else None
    row.label = er.label
    if er.status == ExceptionStatus.RESOLVED:
        row.status = "resolved"
        row.resolution_code = er.resolution_code.value if er.resolution_code else None
    elif row.resolution_code in ("resolved_by_credit",) or row.status == "auto_closed":
        row.status, row.resolution_code = "open", None
    elif row.status not in PERSON_RESOLUTIONS:
        row.status = "open"


def _event(
    s: Session,
    tenant_id: uuid.UUID,
    row: ExceptionRow,
    run: MatchRun,
    event: str,
    from_status: str | None,
    to_status: str | None,
) -> None:
    s.add(
        ExceptionEvent(
            tenant_id=tenant_id,
            exception_id=row.id,
            event=event,
            actor_job_id=str(run.id),
            from_status=from_status,
            to_status=to_status,
            match_run_id=run.id,
        )
    )
