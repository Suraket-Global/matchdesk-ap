"""Delete one uploaded invoice or credit-note document (B12; schema.md section 8; TRD 12).

A soft deletion: ``documents.removed_at``, ``removed_by``, ``removed_reason`` are set and the row and
the original file stay until the retention rules remove them (account deletion; the archive lists the
document as deleted). Nothing is overwritten:

- the current results of the document's lines are retired (kept as history, no current one);
- its open or resolved exceptions are closed with the event ``document_removed`` (who, why), and a
  waiver waiting for approval on one of them is withdrawn;
- every other invoice and credit note of the same suppliers is re-evaluated by a new match run, so a
  duplicate, a credit or a cumulative quantity that used the document is decided again without it.

A clerk or a controller may delete a document no one has accepted yet. A document accepted into
matching (gates passed, or confirmed by a person) needs the controller and a reason. A document in
an approved report stays in that report (approved reports are immutable); later drafts of the period
list it as deleted after approval (``reporting.backtest``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, ForbiddenError
from matchdesk.exceptions.models import Approval, ExceptionEvent, ExceptionRow
from matchdesk.exceptions.store import retire_line_result
from matchdesk.exceptions.triggers import related_invoices, request_runs
from matchdesk.intake.models import DocumentRow, InvoiceLineRow, InvoiceRow
from matchdesk.qbo import processing_allowed
from matchdesk.tenancy import lock_for_update

# Accepted into matching: the arithmetic gates passed or a person confirmed the document.
ACCEPTED = frozenset({"passed", "human_confirmed", "human_confirmed_inconsistent"})
# Still being read by the worker: a deletion now would race the extraction.
IN_PROGRESS = frozenset({"queued", "running", "retry_wait"})
REASON_MAX = 500


def removal_rule(doc: DocumentRow, invoices: list[InvoiceRow]) -> dict[str, Any]:
    """What deleting this document needs, for the screen and the endpoint alike."""
    accepted = any(i.verification_status in ACCEPTED for i in invoices)
    blocked = None
    if doc.purpose != "invoice":
        blocked = "only an invoice or credit-note document can be deleted here"
    elif doc.removed_at is not None:
        blocked = "this document was already deleted"
    elif doc.state in IN_PROGRESS:
        blocked = "this document is still being read; try again when it is ready"
    return {
        "accepted": accepted,
        "needs_controller": accepted,
        "reason_required": accepted,
        "blocked": blocked,
    }


def remove_document(
    s: Session,
    tenant_id: uuid.UUID,
    doc: DocumentRow,
    user_id: uuid.UUID,
    role: str,
    reason: str | None,
) -> dict[str, Any]:
    """Delete ``doc`` (soft) and re-evaluate what used it. Returns what changed."""
    lock_for_update(s, doc)  # two deletions of one document: the second sees the first
    invoices = list(s.scalars(select(InvoiceRow).where(InvoiceRow.document_id == doc.id)).all())
    rule = removal_rule(doc, invoices)
    if rule["blocked"]:
        raise ConflictError(rule["blocked"])
    why = (reason or "").strip() or None
    if why is not None and len(why) > REASON_MAX:
        raise ValueError(f"the reason is longer than {REASON_MAX} characters")
    if rule["needs_controller"] and role != "controller":
        raise ForbiddenError("a document already accepted into matching is deleted by the controller")
    if rule["reason_required"] and why is None:
        raise ValueError("a reason is required to delete a document already accepted into matching")

    now = datetime.now(UTC)
    doc.removed_at, doc.removed_by, doc.removed_reason = now, user_id, why
    inv_ids = [i.id for i in invoices]
    retired = 0
    for line_id in s.scalars(select(InvoiceLineRow.id).where(InvoiceLineRow.invoice_id.in_(inv_ids))).all():
        retired += retire_line_result(s, line_id)
    closed: list[uuid.UUID] = []
    withdrawn = 0
    for e in s.scalars(select(ExceptionRow).where(ExceptionRow.invoice_id.in_(inv_ids))).all():
        if e.status == "auto_closed":
            continue
        before = e.status
        for a in s.scalars(
            select(Approval).where(Approval.exception_id == e.id, Approval.status == "pending")
        ).all():
            a.status, a.version = "withdrawn", a.version + 1
            withdrawn += 1
        e.status, e.line_match_id = "auto_closed", None
        e.version += 1
        s.add(
            ExceptionEvent(
                tenant_id=tenant_id,
                exception_id=e.id,
                event="document_removed",
                actor_user_id=user_id,
                from_status=before,
                to_status="auto_closed",
                detail={"document_id": str(doc.id), "reason": why},
            )
        )
        closed.append(e.id)
    s.flush()

    # Re-evaluate every other document of the same suppliers (live documents only).
    others = sorted(set(related_invoices(s, inv_ids)) - set(inv_ids))
    run = None
    if others and processing_allowed(s):
        run = request_runs(s, tenant_id, others, "document_removed", doc.id)
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="document.removed",
        entity_type="document",
        entity_id=doc.id,
        before={
            "state": doc.state,
            "accepted": rule["accepted"],
            "invoices": [
                {"id": str(i.id), "doc_number": i.doc_number, "verification_status": i.verification_status}
                for i in invoices
            ],
        },
        after={
            "reason": why,
            "results_retired": retired,
            "exceptions_closed": len(closed),
            "approvals_withdrawn": withdrawn,
            "match_run_id": str(run.id) if run else None,
        },
    )
    return {
        "document_id": str(doc.id),
        "removed_at": now.isoformat(),
        "reason": why,
        "invoice_ids": [str(i) for i in inv_ids],
        "results_retired": retired,
        "exceptions_closed": len(closed),
        "approvals_withdrawn": withdrawn,
        "match_run_id": str(run.id) if run else None,
    }
