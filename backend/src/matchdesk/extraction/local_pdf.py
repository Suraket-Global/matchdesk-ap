"""Local extractor for text-based PDFs: no network, no model call (T-3.3.2 (b); MH-05; B3).

It reads the PDF's own text layer with ``pypdf`` and fills a field only where a fixed pattern
matches exactly (a labelled header field, or a whole item line whose numbers parse). Everything it
cannot read with certainty is left empty and named in ``unread``; the gate ``required_fields_read``
then sends the document to a person. Free text, including any instruction written into a
document, is never interpreted: it can only fail to match a pattern (HR-01's injection page).

Scanned images and PDFs without a text layer produce an empty reading and go to review.
"""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from matchdesk.extraction.provider import Extracted, ExtractionPermanentError

MAX_PAGES = 60  # TRD 8.7
REQUIRED = ("vendor_name", "doc_number", "doc_date", "total")

_LABELS: dict[str, re.Pattern[str]] = {
    "vendor_name": re.compile(r"^\s*(?:Vendor|Supplier)\s*:\s*(.+?)\s*$", re.I),
    "doc_number": re.compile(
        r"^\s*(?:Invoice|Credit\s+Note)\s+(?:No\.?|Number|#)\s*:?\s*([A-Za-z0-9][\w\-/]*)\s*$", re.I
    ),
    "doc_date": re.compile(r"^\s*(?:Invoice\s+|Credit\s+Note\s+)?Date\s*:\s*(.+?)\s*$", re.I),
    "po_number": re.compile(
        r"^\s*(?:PO|P\.O\.|Purchase\s+Order)\s*(?:No\.?|Number|#)?\s*:\s*([A-Za-z0-9][\w\-/]*)\s*$", re.I
    ),
    "references_invoice_number": re.compile(
        r"^\s*(?:Re|Refers\s+to|References)\s+Invoice\s*:\s*([A-Za-z0-9][\w\-/]*)\s*$", re.I
    ),
    "currency": re.compile(r"^\s*Currency\s*:\s*([A-Z]{3})\s*$"),
    "subtotal": re.compile(r"^\s*Subtotal\s*:\s*(-?[\d,]+\.\d{2})\s*$", re.I),
    "tax_total": re.compile(r"^\s*(?:Tax|GST|GST/PST|HST)\s*(?:Total)?\s*:\s*(-?[\d,]+\.\d{2})\s*$", re.I),
    "total": re.compile(
        r"^\s*(?:Total|Invoice\s+Total|Amount\s+Due|Credit\s+Total)\s*:\s*(-?[\d,]+\.\d{2})\s*$", re.I
    ),
}
_ITEM = re.compile(
    r"^\s*(?P<code>[A-Z0-9][A-Z0-9\-\.]{1,30})\s+(?P<desc>.+?)\s+(?P<qty>-?\d+(?:\.\d{1,4})?)\s+"
    r"(?P<uom>[A-Z]{1,4})\s+(?P<price>-?[\d,]+\.\d{2,6})\s+(?P<amount>-?[\d,]+\.\d{2})\s*$"
)
_CHARGE = re.compile(
    r"^\s*(?P<kind>FREIGHT|FEE|DISCOUNT)\b\s*(?P<desc>.*?)\s+(?P<amount>-?[\d,]+\.\d{2})\s*$"
)
_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y")

# Document type evidence (B6, outside QA finding 1). Only a heading line or a labelled field counts;
# a phrase in free text ("Please request a credit note for returned items") is never evidence.
_HEADING_LINES = 6  # a title is among the first non-empty lines
_HEADINGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("invoice", re.compile(r"^\s*(?:TAX\s+)?INVOICE\s*$", re.I)),
    ("credit_note", re.compile(r"^\s*(?:TAX\s+)?CREDIT\s+(?:NOTE|MEMO)\s*$", re.I)),
)
_TYPE_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("invoice", re.compile(r"^\s*Invoice\s+(?:No\.?|Number|#|Date|Total)\s*:?", re.I)),
    ("credit_note", re.compile(r"^\s*Credit\s+(?:Note|Memo)\s+(?:No\.?|Number|#|Date|Total)\s*:?", re.I)),
    ("credit_note", re.compile(r"^\s*Credit\s+Total\s*:", re.I)),
    ("credit_note", re.compile(r"^\s*(?:Re|Refers\s+to|References)\s+Invoice\s*:", re.I)),
)


def _money(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def _date(text: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def document_type(text: str) -> str | None:
    """``invoice`` or ``credit_note`` from the heading and labelled fields only; ``None`` (unread, so
    the document goes to review) when there is no such evidence or the evidence conflicts."""
    evidence: set[str] = set()
    lines = text.splitlines()
    for raw in [ln for ln in lines if ln.strip()][:_HEADING_LINES]:
        for kind, pat in _HEADINGS:
            if pat.match(raw):
                evidence.add(kind)
    for raw in lines:
        for kind, pat in _TYPE_LABELS:
            if pat.match(raw):
                evidence.add(kind)
    return evidence.pop() if len(evidence) == 1 else None


def read_text_fields(text: str) -> dict[str, Any]:
    """Parse the fixed patterns out of a document's text. Pure; used by the adapter and its tests."""
    out: dict[str, Any] = {}
    doc_type = document_type(text)
    if doc_type is not None:
        out["doc_type"] = doc_type
    lines: list[dict[str, Any]] = []
    for raw in text.splitlines():
        for name, pat in _LABELS.items():
            if name in out:
                continue
            m = pat.match(raw)
            if m:
                value = m.group(1)
                if name == "doc_date":
                    parsed = _date(value)
                    if parsed is not None:
                        out[name] = parsed.isoformat()
                elif name in ("subtotal", "tax_total", "total"):
                    amount = _money(value)
                    if amount is not None:
                        out[name] = amount
                else:
                    out[name] = value.strip()
                break
        else:
            m = _ITEM.match(raw)
            if m:
                qty, price, amount = _money(m["qty"]), _money(m["price"]), _money(m["amount"])
                if qty is not None and price is not None and amount is not None:
                    lines.append(
                        {
                            "line_no": len(lines) + 1,
                            "kind": "item",
                            "supplier_item_code": m["code"],
                            "description": m["desc"].strip(),
                            "qty": qty,
                            "uom": m["uom"],
                            "unit_price": price,
                            "amount": amount,
                        }
                    )
                continue
            m = _CHARGE.match(raw)
            if m and _money(m["amount"]) is not None:
                kind = {"FREIGHT": "freight", "FEE": "fee", "DISCOUNT": "discount"}[m["kind"]]
                lines.append(
                    {
                        "line_no": len(lines) + 1,
                        "kind": kind,
                        "supplier_item_code": None,
                        "description": m["desc"].strip() or kind,
                        "qty": None,
                        "uom": None,
                        "unit_price": None,
                        "amount": _money(m["amount"]),
                    }
                )
    out["lines"] = lines
    unread = [f for f in REQUIRED if f not in out]
    if doc_type is None:
        unread.append("doc_type")
    if not lines:
        unread.append("lines")
    out["unread"] = unread
    return out


class LocalPdfExtractor:
    provider = "local"
    model = "pdf-text-patterns"
    prompt_version = "l1"

    def extract(self, data: bytes) -> Extracted:
        if not data.startswith(b"%PDF-"):
            # An image or another type: nothing can be read with certainty; a person keys it.
            return Extracted(self.provider, self.model, self.prompt_version, {"lines": [], "unread": ["all"]})
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractionPermanentError("password_protected")
            if len(reader.pages) > MAX_PAGES:
                raise ExtractionPermanentError("too_many_pages")
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except PdfReadError as exc:
            raise ExtractionPermanentError("unreadable") from exc
        output = read_text_fields(text)
        output["page_count"] = len(reader.pages)
        return Extracted(self.provider, self.model, self.prompt_version, output)
