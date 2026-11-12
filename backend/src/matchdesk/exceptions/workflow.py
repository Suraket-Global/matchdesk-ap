"""Exception workflow: late receiving evidence, resolutions, waivers, approvals (T-4.2.3; MH-11).

Every change is versioned (``If-Match``), audited and recorded in ``exception_events``; nothing is
overwritten. A waiver never removes an exception from the qualifying total (Decision.md 5.1).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.exceptions.models import Approval, ExceptionRow, LineMatch

OPEN_STATES = ("open", "pending_approval")


def po_lines_with_open_exceptions(s: Session, po_line_ids: Iterable[uuid.UUID]) -> frozenset[uuid.UUID]:
    """PO lines on which an exception is open now: receipts committed for them are late evidence
    and count only after the controller approves (TRD 8.5; IT-28)."""
    ids = list(po_line_ids)
    if not ids:
        return frozenset()
    rows = s.execute(
        select(LineMatch.po_line_id)
        .join(ExceptionRow, ExceptionRow.line_match_id == LineMatch.id)
        .where(LineMatch.po_line_id.in_(ids), ExceptionRow.status.in_(OPEN_STATES))
    ).all()
    return frozenset(r[0] for r in rows if r[0] is not None)


def request_late_receipt_approval(
    s: Session, tenant_id: uuid.UUID, import_id: uuid.UUID, user_id: uuid.UUID, late_lines: int
) -> Approval | None:
    if late_lines <= 0:
        return None
    found = s.scalar(
        select(Approval).where(Approval.receiving_import_id == import_id, Approval.status == "pending")
    )
    if found is not None:
        return found
    approval = Approval(
        tenant_id=tenant_id,
        subject_type="late_receipt",
        receiving_import_id=import_id,
        requested_by=user_id,
        status="pending",
        version=1,
    )
    s.add(approval)
    s.flush()
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="approval.requested",
        entity_type="approval",
        entity_id=approval.id,
        after={"subject": "late_receipt", "lines": late_lines},
    )
    return approval
