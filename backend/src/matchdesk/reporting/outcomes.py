"""Pilot measurement: three separate counts per back-test (PRD M-3a to M-3c, C1 2026-11-11).

1. **Flagged discrepancy**: a qualifying exception on the governing report (what the rules raised).
2. **Controller-confirmed overcharge**: a flagged discrepancy the controller confirmed is a real
   overcharge, with the amount the controller confirmed.
3. **Actual credit recovered**: a confirmed overcharge for which the supplier's credit or refund
   was actually received, with the amount received.

The three are never added together or substituted for one another. They are measured against the
governing report's flagged set, not a later match run: a recovered credit note entered later nets
the exception away on re-matching (``resolved_by_credit``), which would otherwise erase the very
recovery being counted. Pure; amounts are ``Decimal``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from matchdesk.core import ZERO, dec, round_cents
from matchdesk.matching import ExceptionResult

Key = tuple[str, str, str]


class FindingOutcome(StrEnum):
    FLAGGED = "flagged"
    CONTROLLER_CONFIRMED = "controller_confirmed"
    CREDIT_RECOVERED = "credit_recovered"


@dataclass(frozen=True)
class OutcomeCount:
    count: int
    amount: Decimal


@dataclass(frozen=True)
class PilotMeasurement:
    flagged: OutcomeCount
    controller_confirmed: OutcomeCount
    credit_recovered: OutcomeCount


def _positive(amount: Decimal, what: str, key: Key) -> Decimal:
    value = round_cents(dec(amount))
    if value <= ZERO:
        raise ValueError(f"{what} amount for {key} must be positive")
    return value


def measure_findings(
    governing_exceptions: Iterable[ExceptionResult],
    confirmed: Mapping[Key, Decimal],
    recovered: Mapping[Key, Decimal],
) -> PilotMeasurement:
    """``confirmed`` and ``recovered`` map an exception key (``ExceptionResult.key``) to an amount.

    A confirmation must name a flagged discrepancy and may not exceed its reported amount;
    a recovery must name a confirmed overcharge. Either rule broken raises ``ValueError``.
    """
    flagged = {e.key: e for e in governing_exceptions if e.qualifying}
    flagged_total = sum((dec(e.reported_amount) for e in flagged.values()), ZERO)
    conf_total = ZERO
    for key, amount in confirmed.items():
        if key not in flagged:
            raise ValueError(f"confirmed overcharge {key} is not a flagged discrepancy")
        value = _positive(amount, "confirmed", key)
        if value > dec(flagged[key].reported_amount):
            raise ValueError(f"confirmed amount for {key} exceeds the flagged amount")
        conf_total += value
    rec_total = ZERO
    for key, amount in recovered.items():
        if key not in confirmed:
            raise ValueError(f"credit recovered on {key} without a controller-confirmed overcharge")
        rec_total += _positive(amount, "recovered", key)
    return PilotMeasurement(
        flagged=OutcomeCount(len(flagged), round_cents(flagged_total)),
        controller_confirmed=OutcomeCount(len(confirmed), round_cents(conf_total)),
        credit_recovered=OutcomeCount(len(recovered), round_cents(rec_total)),
    )
