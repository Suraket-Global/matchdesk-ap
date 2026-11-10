"""Number normalisation and deterministic document order (MH-08, TRD section 8.5)."""

from __future__ import annotations

import re
from datetime import date

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_DIGIT_RUN = re.compile(r"\d+")


def normalise_number(value: str | None) -> str:
    """Upper-case, letters and digits only, leading zeros of each digit run removed.

    ``INV-01042`` and ``inv 1042`` both become ``INV1042``. A run of only zeros
    keeps one zero.
    """
    if not value:
        return ""
    text = _NON_ALNUM.sub("", value.upper())
    return _DIGIT_RUN.sub(lambda m: m.group(0).lstrip("0") or "0", text)


def normalise_code(value: str | None) -> str:
    """Supplier item codes: upper-case, letters and digits only (zeros kept)."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", value.upper())


def normalise_uom(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def document_order_key(doc_date: date | None, number: str | None, tiebreak: bytes) -> tuple:
    """Order by document date, then normalised number, then file hash. Never upload time.

    A missing date sorts after every dated document, deterministically.
    """
    return (doc_date is None, doc_date or date.max, normalise_number(number), tiebreak)
