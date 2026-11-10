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

from matchdesk.core import ZERO, dec, round_cents
from matchdesk.matching import ExceptionResult, ValueClass

DEFAULT_THRESHOLD = Decimal("500.00")


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
