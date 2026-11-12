"""Exception workflow: late receiving evidence, resolutions, waivers, approvals (T-4.2.3; MH-11).

Every change is versioned (``If-Match``), audited and recorded in ``exception_events``; nothing is
overwritten. A waiver never removes an exception from the qualifying total (Decision.md 5.1).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ConflictError, ForbiddenError, dec
from matchdesk.exceptions.models import Approval, ExceptionEvent, ExceptionRow, ItemAlias, LineMatch
from matchdesk.exceptions.permissions import check_resolution_allowed

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


# --- Resolutions, waivers and approvals (T-4.2.1 (d), T-4.2.3; IT-13, IT-14, IT-22, IT-23, IT-27) ---

PERSON_CODES: dict[str, frozenset[str]] = {
    "receipt_absent": frozenset({"confirmed_not_received", "source_corrected", "waived"}),
    "possible_duplicate": frozenset({"confirmed_duplicate", "not_a_duplicate"}),
    "duplicate": frozenset({"confirmed_duplicate", "source_corrected", "waived"}),
    "qty_over_received": frozenset(
        {"confirmed_overbilling", "confirmed_short_shipment", "source_corrected", "waived"}
    ),
    "qty_over_ordered": frozenset({"confirmed_overbilling", "source_corrected", "waived"}),
    "price_variance": frozenset({"confirmed_overbilling", "source_corrected", "waived"}),
    "unmatched_charge": frozenset({"confirmed_overbilling", "source_corrected", "waived"}),
}
DEFAULT_CODES = frozenset({"source_corrected", "waived"})
# Decisions that change the inputs of the rule engine: the caller requests a re-match.
INPUT_DECISIONS = frozenset({"confirmed_not_received", "confirmed_duplicate", "not_a_duplicate"})
WAIVER_WINDOW = timedelta(days=30)


@dataclass(frozen=True)
class Outcome:
    exception_id: uuid.UUID
    status: str
    result: str  # resolved | waived | pending_approval | skipped
    reason: str | None = None
    approval_id: uuid.UUID | None = None
    rematch: bool = False


class StaleExceptionVersion(ConflictError):
    def __init__(self, current: ExceptionRow) -> None:
        super().__init__("stale version")
        self.current = current


def _event(
    s: Session,
    row: ExceptionRow,
    event: str,
    user_id: uuid.UUID | None,
    before: str | None,
    detail: dict | None = None,
) -> None:
    s.add(
        ExceptionEvent(
            tenant_id=row.tenant_id,
            exception_id=row.id,
            event=event,
            actor_user_id=user_id,
            from_status=before,
            to_status=row.status,
            detail=detail,
        )
    )


def allowed_codes(exc: ExceptionRow) -> frozenset[str]:
    return PERSON_CODES.get(exc.type, DEFAULT_CODES)


def check_code(role: str, exc: ExceptionRow, code: str, *, bulk: bool) -> None:
    check_resolution_allowed(role, exc.type, code, bulk=bulk)
    if code not in allowed_codes(exc):
        raise ForbiddenError(f"{code} is not a resolution for {exc.type}")
    if (
        exc.type == "possible_duplicate" or exc.possibly_credited_bill_id is not None
    ) and role != "controller":
        raise ForbiddenError("only the controller decides a possible duplicate or a possible credit")


def unapproved_waivers(s: Session, user_id: uuid.UUID, now: datetime) -> Decimal:
    """Total a person waived in the last 30 days without the controller's approval (IT-27)."""
    approved = select(Approval.exception_id).where(
        Approval.subject_type == "waiver", Approval.status == "approved"
    )
    total = s.scalar(
        select(func.coalesce(func.sum(ExceptionRow.reported_amount), 0)).where(
            ExceptionRow.resolution_code == "waived",
            ExceptionRow.resolved_by == user_id,
            ExceptionRow.resolved_at >= now - WAIVER_WINDOW,
            ExceptionRow.id.not_in(approved),
        )
    )
    return dec(str(total or 0))


def _waiver_amount(exc: ExceptionRow) -> Decimal:
    return dec(str(exc.reported_amount if exc.reported_amount is not None else exc.variance_amount or 0))


def resolve(
    s: Session,
    exc: ExceptionRow,
    user_id: uuid.UUID,
    role: str,
    code: str,
    note: str | None,
    expected_version: int,
    waiver_limit: Decimal,
    period_cap: Decimal,
    *,
    bulk: bool = False,
    batch_waiver_total: Decimal | None = None,
) -> Outcome:
    """Resolve one exception with a code and note. A clerk's waiver above the item limit, or one that
    takes the clerk's unapproved waivers in 30 days above the cap, becomes pending (MH-11)."""
    if exc.version != expected_version:
        raise StaleExceptionVersion(exc)
    check_code(role, exc, code, bulk=bulk)
    if exc.status != "open":
        raise ConflictError(f"an exception in status {exc.status} cannot be resolved")
    if code == "waived" and not (note or "").strip():
        raise ValueError("a waiver needs a reason")
    now = datetime.now(UTC)
    before = exc.status
    if code == "waived" and role != "controller":
        amount = _waiver_amount(exc)
        reason = None
        if amount > waiver_limit:
            reason = "above_item_limit"
        elif (
            unapproved_waivers(s, user_id, now)
            + (batch_waiver_total if batch_waiver_total is not None else amount)
            > period_cap
        ):
            reason = "above_period_cap"
        if reason is not None:
            approval = Approval(
                tenant_id=exc.tenant_id,
                subject_type="waiver",
                exception_id=exc.id,
                reason=reason,
                requested_by=user_id,
                amount=amount,
                requested_resolution="waived",
                requested_note=note,
                status="pending",
                version=1,
            )
            s.add(approval)
            exc.status = "pending_approval"
            exc.version += 1
            s.flush()
            _event(s, exc, "sent_for_approval", user_id, before, {"reason": reason, "amount": str(amount)})
            write_audit(
                s,
                exc.tenant_id,
                actor_type="user",
                actor_user_id=user_id,
                action="exception.waiver_requested",
                entity_type="exception",
                entity_id=exc.id,
                after={"reason": reason, "amount": str(amount)},
            )
            return Outcome(exc.id, exc.status, "pending_approval", reason, approval.id)
    exc.status = "waived" if code == "waived" else "resolved"
    exc.resolution_code, exc.resolution_note = code, (note or None)
    exc.resolved_by, exc.resolved_at = user_id, now
    exc.version += 1
    s.flush()
    _event(s, exc, "resolved", user_id, before, {"code": code})
    write_audit(
        s,
        exc.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="exception.resolved",
        entity_type="exception",
        entity_id=exc.id,
        after={"code": code, "status": exc.status},
    )
    return Outcome(exc.id, exc.status, exc.status, rematch=code in INPUT_DECISIONS)


def bulk_resolve(
    s: Session,
    items: list[tuple[uuid.UUID, int]],
    user_id: uuid.UUID,
    role: str,
    code: str,
    note: str | None,
    waiver_limit: Decimal,
    period_cap: Decimal,
) -> list[dict]:
    """Per-item results. ``receipt_absent`` is never waived in bulk; the period cap applies to the
    batch total of the waivers (IT-22, IT-27)."""
    rows = {
        e.id: e for e in s.scalars(select(ExceptionRow).where(ExceptionRow.id.in_([i for i, _v in items])))
    }
    eligible: list[tuple[ExceptionRow, int]] = []
    results: list[dict] = []
    for ex_id, version in items:
        row = rows.get(ex_id)
        if row is None:
            results.append({"id": str(ex_id), "result": "skipped", "reason": "not_found"})
            continue
        try:
            check_code(role, row, code, bulk=True)
        except ForbiddenError as exc:
            results.append({"id": str(ex_id), "result": "skipped", "reason": str(exc)})
            continue
        if row.status != "open":
            results.append({"id": str(ex_id), "result": "skipped", "reason": f"status {row.status}"})
            continue
        if row.version != version:
            results.append({"id": str(ex_id), "result": "skipped", "reason": "stale version"})
            continue
        eligible.append((row, version))
    batch_total = sum((_waiver_amount(r) for r, _v in eligible), Decimal("0")) if code == "waived" else None
    for row, version in eligible:
        out = resolve(
            s,
            row,
            user_id,
            role,
            code,
            note,
            version,
            waiver_limit,
            period_cap,
            bulk=True,
            batch_waiver_total=batch_total,
        )
        results.append(
            {
                "id": str(row.id),
                "result": out.result,
                "reason": out.reason,
                "approval_id": str(out.approval_id) if out.approval_id else None,
                "rematch": out.rematch,
            }
        )
    return results


def withdraw(s: Session, exc: ExceptionRow, user_id: uuid.UUID, expected_version: int) -> ExceptionRow:
    if exc.version != expected_version:
        raise StaleExceptionVersion(exc)
    approval = s.scalar(select(Approval).where(Approval.exception_id == exc.id, Approval.status == "pending"))
    if exc.status != "pending_approval" or approval is None:
        raise ConflictError("nothing is waiting for approval")
    if approval.requested_by != user_id:
        raise ForbiddenError("only the requester may withdraw a pending resolution")
    approval.status, approval.version = "withdrawn", approval.version + 1
    before = exc.status
    exc.status = "open"
    exc.version += 1
    s.flush()
    _event(s, exc, "withdrawn", user_id, before)
    return exc


def reopen(
    s: Session, exc: ExceptionRow, user_id: uuid.UUID, role: str, expected_version: int
) -> ExceptionRow:
    """Controller only (IT-23). The earlier resolution stays in the events."""
    if role != "controller":
        raise ForbiddenError("only the controller reopens an exception")
    if exc.version != expected_version:
        raise StaleExceptionVersion(exc)
    if exc.status not in ("resolved", "waived"):
        raise ConflictError(f"an exception in status {exc.status} cannot be reopened")
    before, previous = (
        exc.status,
        {
            "code": exc.resolution_code,
            "by": str(exc.resolved_by) if exc.resolved_by else None,
            "note": exc.resolution_note,
        },
    )
    exc.status, exc.resolution_code, exc.resolution_note = "open", None, None
    exc.resolved_by, exc.resolved_at = None, None
    exc.version += 1
    s.flush()
    _event(s, exc, "reopened", user_id, before, {"previous": previous})
    write_audit(
        s,
        exc.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action="exception.reopened",
        entity_type="exception",
        entity_id=exc.id,
        before=previous,
    )
    return exc


@dataclass(frozen=True)
class Decision:
    approval: Approval
    effect: str  # waiver_applied | waiver_returned | alias_activated | alias_returned | late_receipt_approved | late_receipt_returned
    subject_id: uuid.UUID


def decide(
    s: Session,
    approval: Approval,
    user_id: uuid.UUID,
    role: str,
    approve: bool,
    note: str | None,
    expected_version: int,
    controller_count: int,
) -> Decision:
    """Approve or return (controller). The approver differs from the requester unless the tenant has a
    single controller, recorded as ``self_approved`` (schema.md 4.1)."""
    if role != "controller":
        raise ForbiddenError("only the controller decides approvals")
    if approval.version != expected_version:
        raise ConflictError("stale version")
    if approval.status != "pending":
        raise ConflictError(f"an approval in status {approval.status} cannot be decided")
    self_decision = approval.requested_by == user_id
    if self_decision and controller_count > 1:
        raise ForbiddenError("a requester cannot approve their own request while another controller exists")
    now = datetime.now(UTC)
    approval.status = "approved" if approve else "returned"
    approval.decided_by, approval.decided_at, approval.decision_note = user_id, now, note
    approval.self_approved = self_decision
    approval.version += 1
    effect = ""
    subject: uuid.UUID
    if approval.subject_type == "waiver":
        exc = s.get(ExceptionRow, approval.exception_id)
        assert exc is not None
        subject = exc.id
        before = exc.status
        if approve:
            exc.status, exc.resolution_code = "waived", "waived"
            exc.resolution_note = approval.requested_note or note or "approved waiver"
            exc.resolved_by, exc.resolved_at = approval.requested_by, now
            effect = "waiver_applied"
        else:
            exc.status = "open"
            effect = "waiver_returned"
        exc.version += 1
        s.flush()
        _event(
            s, exc, "approved" if approve else "returned", user_id, before, {"approval_id": str(approval.id)}
        )
    elif approval.subject_type == "alias_conversion":
        alias = s.get(ItemAlias, approval.alias_id)
        assert alias is not None
        subject = alias.id
        if approve:
            alias.status, alias.approved_by = "active", user_id
            effect = "alias_activated"
        else:
            alias.status, alias.valid_to = "returned", now
            effect = "alias_returned"
        alias.version += 1
    else:
        assert approval.receiving_import_id is not None
        subject = approval.receiving_import_id
        effect = "late_receipt_approved" if approve else "late_receipt_returned"
    s.flush()
    write_audit(
        s,
        approval.tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action=f"approval.{approval.status}",
        entity_type="approval",
        entity_id=approval.id,
        after={"subject": approval.subject_type, "self_approved": approval.self_approved},
    )
    return Decision(approval, effect, subject)
