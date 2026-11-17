"""Refund criterion of Decision.md section 5.1 (proposal), as a pure calculation (IT-17 partial).

The qualifying total is the sum of ``reported_amount`` over exceptions marked
``qualifying``. A waiver never lowers it; only evidence (a credit, a corrected
source, a counting receipt) removes an exception from it, which the rule engine
has already applied. The refund is due when the total is below the threshold.
Governing-report immutability (IT-17 (d)) needs ``backtest_reports`` and
``pilot_engagements``, which are not built in B1.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from matchdesk.core import ZERO, ConflictError, dec, round_cents
from matchdesk.matching import ExceptionResult, ValueClass

# The CAD 500 fee of Decision.md section 5 [chat]: the threshold of a CAD account without a pilot
# record. B16: an account in another currency has no default (``reporting.pilot.default_fee``).
DEFAULT_THRESHOLD = Decimal("500.00")


class CurrencyMismatch(ConflictError):
    """B16: a report total and a threshold in two currencies were about to be compared."""


def same_currency(report_code: str, pilot_code: str) -> None:
    """Refuse to compare a report total with a threshold in another currency (B16). Nothing is
    ever converted."""
    if report_code.strip().upper() != pilot_code.strip().upper():
        raise CurrencyMismatch(
            f"The report's figures are in {report_code} and the pilot fee and refund threshold are in "
            f"{pilot_code}. MatchDesk never converts currencies, so the refund cannot be evaluated "
            f"until the pilot record states its fee in {report_code}."
        )


@dataclass(frozen=True)
class RefundCalculation:
    qualifying_total: Decimal
    unverified_total: Decimal
    refund_due: bool


def calculate_refund(
    exceptions: Iterable[ExceptionResult],
    threshold: Decimal = DEFAULT_THRESHOLD,
    waived_line_ids: frozenset[str] = frozenset(),
) -> RefundCalculation:
    """``waived_line_ids`` is accepted only to make explicit that a waiver changes nothing."""
    del waived_line_ids
    excs = list(exceptions)
    qualifying = sum((dec(e.reported_amount) for e in excs if e.qualifying), ZERO)
    unverified = sum((dec(e.reported_amount) for e in excs if e.value_class == ValueClass.UNVERIFIED), ZERO)
    qualifying, unverified = round_cents(qualifying), round_cents(unverified)
    return RefundCalculation(qualifying, unverified, refund_due=qualifying < dec(threshold))
