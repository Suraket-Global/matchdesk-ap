"""Free OCR for scans and photos (owner, 2026-11-18): Tesseract on the server reads the image, the
fixed patterns read the text, and a person always confirms what was read from an image."""

from __future__ import annotations

import io
import shutil
import subprocess
from decimal import Decimal

import pytest
from pypdf import PdfWriter

from matchdesk.core import text_pdf
from matchdesk.extraction import local_pdf
from matchdesk.extraction.local_pdf import LocalPdfExtractor
from matchdesk.extraction.provider import verification_gates

INVOICE_TEXT = "\n".join(
    [
        "INVOICE",
        "Vendor: Fictional Fasteners Ltd",
        "Invoice No: FF-2001",
        "Invoice Date: 2026-11-18",
        "PO Number: 1001",
        "Currency: CAD",
        "HB-M8 Hex bolt M8 60 EA 4.20 252.00",
        "Subtotal: 252.00",
        "Tax: 0.00",
        "Total: 252.00",
    ]
)
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic"


def _blank_pdf() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_a_photo_is_read_by_ocr_and_always_goes_to_a_person(monkeypatch):
    monkeypatch.setattr(local_pdf, "ocr_text", lambda data, is_pdf: INVOICE_TEXT)
    ex = LocalPdfExtractor().extract(PNG)
    out = ex.output
    assert ex.model == "pdf-text-patterns+tesseract"
    assert out["read_from_image"] is True and out["unread"] == []
    assert (out["doc_number"], out["total"]) == ("FF-2001", Decimal("252.00"))
    assert out["lines"][0]["qty"] == Decimal("60")
    gates = verification_gates(out)
    assert gates["line_amounts"] and gates["lines_plus_tax_equals_total"] and gates["required_fields_read"]
    assert gates["read_from_image_confirmed"] is False  # prefilled, but a person confirms


def test_a_scanned_pdf_without_text_is_read_by_ocr(monkeypatch):
    seen: list[bool] = []

    def fake(data: bytes, is_pdf: bool) -> str:
        seen.append(is_pdf)
        return INVOICE_TEXT

    monkeypatch.setattr(local_pdf, "ocr_text", fake)
    out = LocalPdfExtractor().extract(_blank_pdf()).output
    assert seen == [True] and out["read_from_image"] is True and out["page_count"] == 1


def test_a_text_pdf_is_not_sent_to_ocr(monkeypatch):
    monkeypatch.setattr(local_pdf, "ocr_text", lambda *_a, **_k: pytest.fail("OCR on a text PDF"))
    out = LocalPdfExtractor().extract(text_pdf(INVOICE_TEXT.splitlines())).output
    assert "read_from_image" not in out and out["doc_number"] == "FF-2001"
    assert "read_from_image_confirmed" not in verification_gates(out)


def test_without_ocr_an_image_is_left_for_a_person(monkeypatch):
    monkeypatch.setattr(local_pdf, "ocr_text", lambda *_a, **_k: None)
    ex = LocalPdfExtractor().extract(PNG)
    assert ex.output == {"lines": [], "unread": ["all"]} and ex.model == "pdf-text-patterns"
    assert verification_gates(ex.output)["required_fields_read"] is False


def test_ocr_reports_none_when_tesseract_is_missing(monkeypatch):
    monkeypatch.setattr(local_pdf.shutil, "which", lambda _name: None)
    assert local_pdf.ocr_text(PNG, is_pdf=False) is None


@pytest.mark.skipif(
    not (shutil.which("tesseract") and shutil.which("pdftoppm")), reason="needs Tesseract and poppler"
)
def test_real_ocr_reads_a_rendered_invoice(tmp_path):
    """Runs where Tesseract is installed (the server image): render a text PDF to a PNG, then read
    the PNG as a photo."""
    pdf = tmp_path / "inv.pdf"
    pdf.write_bytes(text_pdf(INVOICE_TEXT.splitlines(), font_size=12))
    args = ["pdftoppm", "-r", "300", "-png", "-singlefile", str(pdf), str(tmp_path / "inv")]
    subprocess.run(args, check=True)
    out = LocalPdfExtractor().extract((tmp_path / "inv.png").read_bytes()).output
    assert out["read_from_image"] is True
    assert out.get("doc_number") == "FF-2001" and out.get("total") == Decimal("252.00")
