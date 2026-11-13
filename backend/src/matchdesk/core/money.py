"""Money, unit price and quantity arithmetic (TRD section 8.4).

Amounts are NUMERIC(14,2), unit prices NUMERIC(14,6), quantities NUMERIC(14,4).
In code they are ``Decimal``. Binary floats are refused everywhere here: a float
already carries a rounding error, so accepting one would hide it (UT-09).
Rounding is half-up and applied once, at the end of a calculation.
"""

from __future__ import annotations

import re
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


def round_half_up(value: Decimal, step: Decimal) -> Decimal:
    """Round half up (a half away from zero) to ``step``, for percentages and scores (B10, item 4):
    ``Decimal.quantize`` without a rounding argument rounds half to even."""
    return dec(value).quantize(step, rounding=ROUND_HALF_UP)


def line_amount(qty: Decimal, unit_price: Decimal) -> Decimal:
    """Quantity times unit price, rounded once to cents."""
    return round_cents(dec(qty) * dec(unit_price))


def total(values: list[Decimal]) -> Decimal:
    """Exact sum of Decimals (no rounding)."""
    result = ZERO
    for v in values:
        result += dec(v)
    return result


# ------------------------------------------------------------------ typed or file input (B10, item 3)

_SPACES = str.maketrans({" ": " ", " ": " ", " ": " "})


def parse_typed_decimal(text: str | None, places: int = 2, whole: int = 12, negative: bool = True) -> str:
    """A number as a person types it or a file holds it, as a plain decimal string ("1,000.50" ->
    "1000.50"). The same rules as the web app's ``parseNumberInput`` (shared fixture
    ``fixtures/decimal_cases.json``): commas or spaces only between groups of three digits before a
    dot; a comma is never a decimal mark, so "1.000,5" and "1,5" are refused instead of being read
    as 1.0005 or 15; no letters, exponents, NaN or infinity; at most ``places`` decimals and ``whole``
    digits before the point. Empty input is "". Raises ``ValueError`` with the reason."""
    s = (text or "").translate(_SPACES).strip()
    if s == "":
        return ""
    s = re.sub(r"^(?i:cad|\$)\s*", "", s)
    sign = ""
    if s[:1] in ("-", "−"):
        sign, s = "-", s[1:].strip()
    if s == "":
        raise ValueError("type a number after the minus sign")
    if " " in s:
        if not re.fullmatch(r"\d{1,3}( \d{3})+(\.\d+)?", s):
            raise ValueError("spaces go only between groups of three digits")
        s = s.replace(" ", "")
    if "," in s:
        if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s):
            s = s.replace(",", "")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})*,\d+", s):
            raise ValueError("use a dot for decimals: 1000.50, not 1.000,50")
        else:
            raise ValueError("commas go only between groups of three digits")
    if not re.fullmatch(r"\d*\.?\d*", s) or s == ".":
        raise ValueError("use digits, with a dot for decimals")
    w, _, f = s.partition(".")
    if len(f) > places:
        raise ValueError(f"at most {places} decimal places")
    w = w.lstrip("0") or "0"
    if len(w) > whole:
        raise ValueError(f"too large: at most {whole} digits before the decimal point")
    zero = set(w + f) <= {"0"}
    if sign and not zero and not negative:
        raise ValueError("no negative number here")
    return f"{'-' if sign and not zero else ''}{w}{'.' + f if f else ''}"
