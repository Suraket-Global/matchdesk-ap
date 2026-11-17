"""Pilot record (T-5.1.3; schema.md pilot_engagements; Decision.md 5.1, proposal).

One pilot engagement per tenant: price, period, refund condition and threshold, the signed-terms
reference, payment and outcome. The operator creates and edits it (operator session, policy of
schema.md 4.3). The governing report version is chosen once by a controller from the tenant's
approved versions; at that moment the refund criterion is evaluated from that version's stored
qualifying total against the threshold of this record, never a figure from a request, and the
result is stored with it. A trigger refuses any later change of the version or its result.

B16 (2026-11-17): the fee and the threshold are in the account's currency (``currency``), and the
threshold equals the fee (Decision.md 5.1). A CAD account's fee defaults to CAD 500 (Decision.md
section 5); an account in any other currency has no default, so the operator enters its fee. The
refund is evaluated only when the report's currency is the pilot's: never converted, never mixed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from matchdesk.core import ConflictError, dec, round_cents
from matchdesk.intake.models import UsageEvent
from matchdesk.reporting.models import BacktestReport, PilotEngagement
from matchdesk.reporting.refund import DEFAULT_THRESHOLD, same_currency
from matchdesk.tenancy import advisory_lock, tenant_currency

# Decision.md section 5: the pilot is CAD 500 [chat]. Only a CAD account has a default fee; the
# owner sets the fee of an account in another currency (B16), so none is invented here.
DEFAULT_FEES: dict[str, Decimal] = {"CAD": DEFAULT_THRESHOLD}

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


@dataclass(frozen=True)
class RefundTerms:
    """The refund threshold and its currency: the pilot record's, or the CAD default without one."""

    threshold: Decimal
    currency: str
    from_record: bool


def default_fee(currency: str) -> Decimal | None:
    """The pilot fee a new record starts with: CAD 500 for a CAD account, none otherwise (B16)."""
    return DEFAULT_FEES.get(currency.upper())


def refund_terms(s: Session, tenant_id: uuid.UUID) -> RefundTerms:
    """The threshold of the tenant's pilot record in its currency. Without a record, the default of
    the account's currency; an account whose currency has no default has no threshold yet."""
    pilot = get_pilot(s, tenant_id)
    if pilot is not None:
        return RefundTerms(dec(pilot.refund_threshold), pilot.currency, True)
    code = tenant_currency(s, tenant_id)
    fee = default_fee(code)
    if fee is None:
        raise ConflictError(
            f"No pilot fee is recorded for this {code} account yet, so there is no refund threshold. "
            f"MatchDesk enters the fee in {code} on the pilot record."
        )
    return RefundTerms(fee, code, False)


def threshold_for(s: Session, tenant_id: uuid.UUID) -> Decimal:
    """The refund threshold of the tenant's pilot record; the default only when there is none."""
    return refund_terms(s, tenant_id).threshold


def report_currency(s: Session, report: BacktestReport) -> str:
    """The currency of a report version's figures: stored with it since B16; before, the account's
    (match runs use the account's currency since B15)."""
    return (report.currency or tenant_currency(s, report.tenant_id)).upper()


def _fee(v: Any) -> Decimal:
    """A positive amount with at most two decimals; never rounded into shape (B16)."""
    d = dec(str(v))
    if d <= 0:
        raise ValueError("the pilot fee must be more than 0")
    if d != d.quantize(Decimal("0.01")):
        raise ValueError("the pilot fee has at most 2 decimal places")
    return round_cents(d)


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in EDITABLE:
        if k not in values or (k in ("price", "refund_threshold") and values[k] is None):
            continue
        v = values[k]
        if k in ("price", "refund_threshold"):
            v = _fee(v)
        elif k in ("period_start", "period_end"):
            v = v if isinstance(v, date) else date.fromisoformat(str(v))
        elif isinstance(v, str):
            v = v.strip() or None
        out[k] = v
    return out


def save_pilot(
    s: Session,
    tenant_id: uuid.UUID,
    values: dict[str, Any],
    expected_version: int | None,
    currency: str | None = None,
) -> tuple[PilotEngagement, dict[str, Any] | None, dict[str, Any]]:
    """Create (``expected_version`` None) or update the record. Returns it with before and after.

    B16: the record's currency is the account's (``currency``, or ``tenants.currency``); the fee
    defaults only for a CAD account; the refund threshold is the fee. Once the governing version is
    set, the fee, its currency and the threshold are fixed (database trigger)."""
    code = (currency or tenant_currency(s, tenant_id)).strip().upper()
    clean = _clean(values)
    threshold_in = clean.pop("refund_threshold", None)
    price_in = clean.pop("price", None)
    pilot = get_pilot(s, tenant_id)
    if pilot is None:
        if expected_version not in (None, 0):
            raise PilotVersionConflict({})
        start = clean.get("period_start")
        end = clean.get("period_end")
        price = price_in if price_in is not None else default_fee(code)
        if price is None:
            raise ValueError(f"enter the pilot fee in {code}: a {code} account has no default fee")
        if start is None or end is None:
            raise ValueError("price, period start and period end are required")
        _threshold_is_fee(threshold_in, price)
        pilot = PilotEngagement(
            tenant_id=tenant_id,
            refund_condition=clean.pop("refund_condition", None) or DEFAULT_CONDITION,
            price=price,
            refund_threshold=price,
            currency=code,
            **clean,
        )
        s.add(pilot)
        s.flush()
        return pilot, None, describe_pilot(pilot)
    if expected_version != pilot.version:
        raise PilotVersionConflict(describe_pilot(pilot))
    before = describe_pilot(pilot)
    if pilot.governing_report_id is not None:
        if (
            code != pilot.currency
            or (price_in is not None and price_in != dec(pilot.price))
            or (threshold_in is not None and threshold_in != dec(pilot.refund_threshold))
        ):
            raise ConflictError(
                "the pilot fee, its currency and the refund threshold are fixed once the governing "
                "version is set"
            )
    else:
        if code != pilot.currency and price_in is None:
            raise ValueError(
                f"the account is in {code} and this pilot record is in {pilot.currency}: enter the "
                f"pilot fee in {code}"
            )
        price = price_in if price_in is not None else round_cents(dec(pilot.price))
        _threshold_is_fee(threshold_in, price)
        pilot.price, pilot.refund_threshold, pilot.currency = price, price, code
    for k, v in clean.items():
        setattr(pilot, k, v if k != "refund_condition" or v else pilot.refund_condition)
    if pilot.period_end < pilot.period_start:
        raise ValueError("the pilot ends before it starts")
    pilot.version += 1
    pilot.updated_at = datetime.now(UTC)
    s.flush()
    return pilot, before, describe_pilot(pilot)


def _threshold_is_fee(threshold: Decimal | None, fee: Decimal) -> None:
    if threshold is not None and threshold != fee:
        raise ValueError("the refund threshold is the pilot fee (Decision.md 5.1); it is not set apart")


def set_governing(
    s: Session, tenant_id: uuid.UUID, report: BacktestReport, user_id: uuid.UUID
) -> PilotEngagement:
    """Make an approved version the governing one and evaluate the refund on it, once."""
    advisory_lock(s, f"pilot:governing:{tenant_id}")  # B14 (m1): two presses, one decision
    pilot = get_pilot(s, tenant_id)
    if pilot is not None:
        s.refresh(pilot)
    if pilot is None:
        raise ConflictError("there is no pilot record for this account yet")
    if pilot.governing_report_id is not None:
        if pilot.governing_report_id == report.id:
            return pilot
        raise ConflictError("the governing version is already set and cannot change")
    if report.status != "approved" or report.approved_at is None:
        raise ConflictError("only an approved report version can govern the refund")
    same_currency(report_currency(s, report), pilot.currency)  # B16: never across currencies
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
        # B16: the currency of the fee, the threshold and the qualifying amount stored with them.
        "currency": p.currency,
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
