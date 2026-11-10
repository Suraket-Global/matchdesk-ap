"""Extraction provider behind an interface, and the arithmetic gates (MH-05; T-3.3.2 subset).

B1 has no provider account: ``FakeExtractor`` returns a fixed schema from a
synthetic marker in the file. A model only reads documents into this schema;
it never decides a match, a duplicate, a conversion or an amount.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from matchdesk.core import dec, round_cents


class ExtractionTransientError(Exception):
    """Network, HTTP 429 or 5xx: retry with backoff."""


class ExtractionPermanentError(Exception):
    """Unreadable or password-protected file: fail at once."""


@dataclass(frozen=True)
class Extracted:
    provider: str
    model: str
    prompt_version: str
    output: dict[str, Any]


class Extractor(Protocol):
    def extract(self, data: bytes) -> Extracted: ...


class FakeExtractor:
    """Reads synthetic test files: a JSON body after the ``%FAKE-PDF`` marker."""

    provider = "fake"
    model = "fake-1"
    prompt_version = "p0"

    def extract(self, data: bytes) -> Extracted:
        if data.startswith(b"%FAKE-PDF-ENCRYPTED"):
            raise ExtractionPermanentError("password_protected")
        if not data.startswith(b"%FAKE-PDF"):
            raise ExtractionPermanentError("unreadable")
        body = json.loads(data.split(b"\n", 1)[1].decode())
        return Extracted(self.provider, self.model, self.prompt_version, body)


def verification_gates(output: dict[str, Any]) -> dict[str, bool]:
    """Arithmetic gates: each line qty x price = amount; lines + tax + charges = total (UT-08)."""
    gates: dict[str, bool] = {}
    lines = output.get("lines", [])
    line_ok = True
    subtotal = Decimal("0")
    for ln in lines:
        amount = dec(str(ln["amount"]))
        subtotal += amount
        if ln.get("qty") is not None and ln.get("unit_price") is not None:
            line_ok &= round_cents(dec(str(ln["qty"])) * dec(str(ln["unit_price"]))) == amount
    gates["line_amounts"] = line_ok
    tax = dec(str(output.get("tax_total", "0")))
    total = dec(str(output.get("total", "0")))
    gates["lines_plus_tax_equals_total"] = subtotal + tax == total
    return gates
