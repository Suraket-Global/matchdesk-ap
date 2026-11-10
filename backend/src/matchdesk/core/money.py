"""Money, unit price and quantity arithmetic (TRD section 8.4).

Amounts are NUMERIC(14,2), unit prices NUMERIC(14,6), quantities NUMERIC(14,4).
In code they are ``Decimal``. Binary floats are refused everywhere here: a float
already carries a rounding error, so accepting one would hide it (UT-09).
Rounding is half-up and applied once, at the end of a calculation.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
PRICE_STEP = Decimal("0.000001")
QTY_STEP = Decimal("0.0001")
ZERO = Decimal("0")


class FloatNotAllowedError(TypeError):
    """Raised when a binary float reaches money or quantity code."""


def dec(value: Decimal | int | str) -> Decimal:
    """Convert ``value`` to ``Decimal``; refuse floats and booleans."""
    if isinstance(value, bool):
        raise TypeError("booleans are not amounts")
    if isinstance(value, float):
        raise FloatNotAllowedError("binary floats are not allowed in money or quantity arithmetic")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("amount must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal number: {value!r}") from exc
        if not result.is_finite():
            raise ValueError("amount must be finite")
        return result
    raise TypeError(f"unsupported amount type: {type(value).__name__}")


def round_cents(value: Decimal) -> Decimal:
    """Round half-up to cents (NUMERIC(14,2))."""
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_price(value: Decimal) -> Decimal:
    """Round half-up to six decimals (NUMERIC(14,6))."""
    return dec(value).quantize(PRICE_STEP, rounding=ROUND_HALF_UP)


def round_qty(value: Decimal) -> Decimal:
    """Round half-up to four decimals (NUMERIC(14,4))."""
    return dec(value).quantize(QTY_STEP, rounding=ROUND_HALF_UP)


def line_amount(qty: Decimal, unit_price: Decimal) -> Decimal:
    """Quantity times unit price, rounded once to cents."""
    return round_cents(dec(qty) * dec(unit_price))


def total(values: list[Decimal]) -> Decimal:
    """Exact sum of Decimals (no rounding)."""
    result = ZERO
    for v in values:
        result += dec(v)
    return result
