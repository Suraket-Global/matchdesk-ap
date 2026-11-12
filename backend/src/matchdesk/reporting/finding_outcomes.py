"""Finding outcomes on the governing report (PRD M-3b, M-3c; schema.md 3.6 ``finding_outcomes``; B9).

After the governing version is chosen, the controller records, per flagged discrepancy, that it was
confirmed as an overcharge (with the confirmed amount) and later that the supplier's credit was
recovered (with the amount and the credit note or the QuickBooks credit reference). Rows are
insert-only; the database refuses amounts above the finding or the confirmation and any finding
outside the governing version. The three counts stay apart: flagged (the report's own figure),
controller-confirmed and credit recovered; none is ever added to another or written back into the
report, whose figures never change.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from matchdesk.audit import write_audit
from matchdesk.core import ZERO, ConflictError, ForbiddenError, dec, round_cents
from matchdesk.intake.models import DocumentRow, InvoiceRow
from matchdesk.reporting.models import FindingOutcomeRow, PilotEngagement, ReportFinding

FLAGGED_SECTIONS = ("finding", "not_received")


def governing_report_id(s: Session) -> uuid.UUID | None:
    return s.scalar(select(PilotEngagement.governing_report_id))


def outcomes_for(s: Session, report_id: uuid.UUID) -> dict[uuid.UUID, dict[str, FindingOutcomeRow]]:
    rows = s.execute(
        select(FindingOutcomeRow)
        .join(ReportFinding, ReportFinding.id == FindingOutcomeRow.report_finding_id)
        .where(ReportFinding.report_id == report_id)
    ).scalars()
    out: dict[uuid.UUID, dict[str, FindingOutcomeRow]] = {}
    for o in rows:
        out.setdefault(o.report_finding_id, {})[o.outcome] = o
    return out


def describe_outcome(o: FindingOutcomeRow | None, names: dict[uuid.UUID, str]) -> dict[str, Any] | None:
    if o is None:
        return None
    return {
        "amount": str(o.amount),
        "recorded_by": str(o.recorded_by),
        "recorded_by_name": names.get(o.recorded_by),
        "recorded_at": o.created_at.isoformat(),
        "credit_document_id": str(o.credit_document_id) if o.credit_document_id else None,
        "credit_reference": o.credit_reference,
        "note": o.note,
    }


def outcome_totals(s: Session, report_id: uuid.UUID) -> dict[str, dict[str, str | int]]:
    """The three pilot counts of one report version, each with its dollar total, kept apart."""
    findings = s.scalars(
        select(ReportFinding).where(
            ReportFinding.report_id == report_id, ReportFinding.section.in_(FLAGGED_SECTIONS)
        )
    ).all()
    outcomes = outcomes_for(s, report_id)

    def total(kind: str) -> tuple[int, Decimal]:
        vals = [o[kind].amount for o in outcomes.values() if kind in o]
        return len(vals), round_cents(sum((dec(v) for v in vals), ZERO))

    conf_n, conf_amt = total("controller_confirmed")
    rec_n, rec_amt = total("credit_recovered")
    flagged_amt = round_cents(sum((dec(f.amount) for f in findings), ZERO))
    return {
        "flagged": {"count": len(findings), "amount": str(flagged_amt)},
        "controller_confirmed": {"count": conf_n, "amount": str(conf_amt)},
        "credit_recovered": {"count": rec_n, "amount": str(rec_amt)},
    }


def record_outcome(
    s: Session,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    finding: ReportFinding,
    outcome: str,
    amount: Decimal,
    credit_document_id: uuid.UUID | None = None,
    credit_reference: str | None = None,
    note: str | None = None,
) -> FindingOutcomeRow:
    """Record one outcome (controller only). The checks below give the reason in words; the trigger
    ``finding_outcomes_rules`` enforces the same rules in the database."""
    if role != "controller":
        raise ForbiddenError("only the controller records what happened to a finding")
    if outcome not in ("controller_confirmed", "credit_recovered"):
        raise ValueError("outcome must be controller_confirmed or credit_recovered")
    value = round_cents(dec(amount))
    if value <= ZERO:
        raise ValueError("the amount must be above zero")
    if finding.section not in FLAGGED_SECTIONS:
        raise ValueError("only a flagged discrepancy (a finding or not received) can be followed")
    if governing_report_id(s) != finding.report_id:
        raise ConflictError("outcomes are recorded on the governing report version only")
    existing = outcomes_for(s, finding.report_id).get(finding.id, {})
    if outcome in existing:
        raise ConflictError(
            "this outcome is already recorded for the finding; recorded outcomes never change"
        )
    if outcome == "controller_confirmed" and value > dec(finding.amount):
        raise ValueError(f"the confirmed amount is above the flagged amount {finding.amount}")
    ref = (credit_reference or "").strip() or None
    if outcome == "credit_recovered":
        confirmed = existing.get("controller_confirmed")
        if confirmed is None:
            raise ConflictError("confirm the overcharge before recording the credit recovered")
        if value > dec(confirmed.amount):
            raise ValueError(f"the recovered amount is above the confirmed amount {confirmed.amount}")
        if credit_document_id is None and ref is None:
            raise ValueError("name the credit note or the QuickBooks credit reference")
        if credit_document_id is not None:
            doc = s.get(InvoiceRow, credit_document_id)
            if doc is None or doc.doc_type != "credit_note":
                raise ValueError("the credit document must be a credit note of this account")
            credit_document_id = doc.document_id  # the stored file (documents), not the invoice row
            if s.get(DocumentRow, credit_document_id) is None:
                raise ValueError("the credit note's file is missing")
    row = FindingOutcomeRow(
        tenant_id=tenant_id,
        report_finding_id=finding.id,
        outcome=outcome,
        amount=value,
        recorded_by=user_id,
        credit_document_id=credit_document_id,
        credit_reference=ref,
        note=(note or "").strip() or None,
    )
    s.add(row)
    try:
        s.flush()
    except IntegrityError as exc:  # the database rule (trigger or unique key) refused it
        reason = str(getattr(exc, "orig", exc)).splitlines()[0]
        raise ConflictError(f"the outcome was refused: {reason}") from None
    write_audit(
        s,
        tenant_id,
        actor_type="user",
        actor_user_id=user_id,
        action=f"finding.{outcome}",
        entity_type="report_finding",
        entity_id=finding.id,
        after={"amount": str(value), "credit_reference": ref, "note": row.note},
    )
    return row
