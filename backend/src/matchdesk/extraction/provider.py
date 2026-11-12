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

from matchdesk.core import Settings, dec, round_cents


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
        # Amounts are read as Decimal, never as binary floats (B1-007).
        body = json.loads(data.split(b"\n", 1)[1].decode(), parse_float=Decimal, parse_int=Decimal)
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
    if "subtotal" in output and output["subtotal"] is not None:
        gates["subtotal_equals_lines"] = dec(str(output["subtotal"])) == subtotal
    if "unread" in output:
        # Adapters that report what they could not read with certainty (the local PDF reader):
        # any unread required field sends the document to a person (MH-05).
        gates["required_fields_read"] = not output["unread"]
    return gates


def extractor_from_settings(settings: Settings) -> Extractor:
    """``fake`` for tests; ``local`` reads text PDFs without network or model; ``provider`` is a hosted
    model, deferred (needs an account and no-training terms), so it refuses to start."""
    if settings.extractor == "fake":
        return FakeExtractor()
    if settings.extractor == "local":
        from matchdesk.extraction.local_pdf import LocalPdfExtractor

        local: Extractor = LocalPdfExtractor()
        return local
    raise ExtractionNotConfiguredError(
        "hosted extraction provider not configured (deferred: needs an account; T-1.1.3)"
    )


class ExtractionNotConfiguredError(RuntimeError):
    """The hosted provider adapter is selected but has no account or key."""
