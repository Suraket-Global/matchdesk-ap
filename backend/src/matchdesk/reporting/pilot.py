"""Pilot record (T-5.1.3; schema.md pilot_engagements; Decision.md 5.1, proposal).

One pilot engagement per tenant: price, period, refund condition and threshold, the signed-terms
reference, payment and outcome. The operator creates and edits it (operator session, policy of
schema.md 4.3). The governing report version is chosen once by a controller from the tenant's
approved versions; at that moment the refund criterion is evaluated from that version's stored
qualifying total against the threshold of this record, never a figure from a request, and the
result is stored with it. A trigger refuses any later change of the version or its result.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.core import ConflictError, dec, round_cents
from matchdesk.intake.models import UsageEvent
from matchdesk.reporting.models import BacktestReport, PilotEngagement
from matchdesk.reporting.refund import DEFAULT_THRESHOLD

EDITABLE = (
    "price",
    "period_start",
    "period_end",
    "refund_condition",
    "refund_threshold",
    "signed_terms_ref",
    "signed_by_name",
    "signed_by_role",
    "delivery_mode",
    "payment_status",
    "outcome",
)
DEFAULT_CONDITION = (
    "Refunded in full if the governing approved back-test report finds qualifying discrepancies "
    "below the refund threshold."
)


class PilotVersionConflict(Exception):
    def __init__(self, current: dict[str, Any]) -> None:
        super().__init__("pilot record changed")
        self.current = current


def get_pilot(s: Session, tenant_id: uuid.UUID) -> PilotEngagement | None:
    return s.scalar(select(PilotEngagement).where(PilotEngagement.tenant_id == tenant_id))


def threshold_for(s: Session, tenant_id: uuid.UUID) -> Decimal:
    """The refund threshold of the tenant's pilot record; the default only when there is none."""
    pilot = get_pilot(s, tenant_id)
    return dec(pilot.refund_threshold) if pilot is not None else DEFAULT_THRESHOLD


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in EDITABLE:
        if k not in values:
            continue
        v = values[k]
        if k in ("price", "refund_threshold"):
            v = round_cents(dec(str(v)))
            if v < 0:
                raise ValueError(f"{k} cannot be negative")
        elif k in ("period_start", "period_end"):
            v = v if isinstance(v, date) else date.fromisoformat(str(v))
        elif isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    return out


def save_pilot(
    s: Session, tenant_id: uuid.UUID, values: dict[str, Any], expected_version: int | None
) -> tuple[PilotEngagement, dict[str, Any] | None, dict[str, Any]]:
    """Create (``expected_version`` None) or update the record. Returns it with before and after.
    The threshold cannot change once the governing version is set (database trigger)."""
    clean = _clean(values)
    pilot = get_pilot(s, tenant_id)
    if pilot is None:
        if expected_version not in (None, 0):
            raise PilotVersionConflict({})
        start = clean.get("period_start")
        end = clean.get("period_end")
        if start is None or end is None or "price" not in clean:
            raise ValueError("price, period start and period end are required")
        pilot = PilotEngagement(
            tenant_id=tenant_id,
            refund_condition=clean.pop("refund_condition", None) or DEFAULT_CONDITION,
            refund_threshold=clean.pop("refund_threshold", None) or DEFAULT_THRESHOLD,
            **clean,
        )
        s.add(pilot)
        s.flush()
        return pilot, None, describe_pilot(pilot)
    if expected_version != pilot.version:
        raise PilotVersionConflict(describe_pilot(pilot))
    before = describe_pilot(pilot)
    if pilot.governing_report_id is not None and "refund_threshold" in clean:
        if dec(clean["refund_threshold"]) != dec(pilot.refund_threshold):
            raise ConflictError("the refund threshold is fixed once the governing version is set")
        clean.pop("refund_threshold")
    for k, v in clean.items():
        setattr(pilot, k, v if k != "refund_condition" or v else pilot.refund_condition)
    if pilot.period_end < pilot.period_start:
        raise ValueError("the pilot ends before it starts")
    pilot.version += 1
    pilot.updated_at = datetime.now(UTC)
    s.flush()
    return pilot, before, describe_pilot(pilot)


def set_governing(
    s: Session, tenant_id: uuid.UUID, report: BacktestReport, user_id: uuid.UUID
) -> PilotEngagement:
    """Make an approved version the governing one and evaluate the refund on it, once."""
    pilot = get_pilot(s, tenant_id)
    if pilot is None:
        raise ConflictError("there is no pilot record for this account yet")
    if pilot.governing_report_id is not None:
        if pilot.governing_report_id == report.id:
            return pilot
        raise ConflictError("the governing version is already set and cannot change")
    if report.status != "approved" or report.approved_at is None:
        raise ConflictError("only an approved report version can govern the refund")
    qualifying = round_cents(dec(report.qualifying_amount or 0))
    pilot.governing_report_id = report.id
    pilot.governing_set_by = user_id
    pilot.refund_qualifying_amount = qualifying
    pilot.refund_due = qualifying < dec(pilot.refund_threshold)
    pilot.refund_determined_at = datetime.now(UTC)
    pilot.version += 1
    pilot.updated_at = pilot.refund_determined_at
    s.flush()
    return pilot


def usage_by_month(s: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Billable units per month and kind (IT-26). Readable in the tenant and by the operator."""
    rows = s.execute(
        select(UsageEvent.unit_month, UsageEvent.kind, func.count())
        .where(UsageEvent.tenant_id == tenant_id)
        .group_by(UsageEvent.unit_month, UsageEvent.kind)
        .order_by(UsageEvent.unit_month)
    ).all()
    months: dict[date, dict[str, int]] = {}
    for month, kind, n in rows:
        months.setdefault(month, {"invoice": 0, "credit_note": 0})[kind] = int(n)
    return [
        {"month": m.isoformat(), **k, "units": k["invoice"] + k["credit_note"]} for m, k in months.items()
    ]


def describe_pilot(p: PilotEngagement | None) -> dict[str, Any]:
    if p is None:
        return {}

    def money(v: Decimal | None) -> str | None:
        return str(round_cents(dec(v))) if v is not None else None

    return {
        "id": str(p.id),
        "price": money(p.price),
        "period_start": p.period_start.isoformat(),
        "period_end": p.period_end.isoformat(),
        "refund_condition": p.refund_condition,
        "refund_threshold": money(p.refund_threshold),
        "signed_terms_ref": p.signed_terms_ref,
        "signed_by_name": p.signed_by_name,
        "signed_by_role": p.signed_by_role,
        "delivery_mode": p.delivery_mode,
        "governing_report_id": str(p.governing_report_id) if p.governing_report_id else None,
        "refund_determined_at": p.refund_determined_at.isoformat() if p.refund_determined_at else None,
        "refund_qualifying_amount": money(p.refund_qualifying_amount),
        "refund_due": p.refund_due,
        "payment_status": p.payment_status,
        "outcome": p.outcome,
        "version": p.version,
    }
