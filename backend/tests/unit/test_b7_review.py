"""Regression tests for the B6 A-to-Z review of 2026-11-13 (unit level). IDs are the review's."""

from __future__ import annotations

from matchdesk.extraction.local_pdf import document_type


def test_m9_prose_about_a_credit_note_is_not_a_label() -> None:
    doc = "\n".join(
        [
            "INVOICE",
            "Invoice No: SS-5120",
            "Credit note number will be sent on request",
            "Credit note number to follow",
        ]
    )
    assert document_type(doc) == "invoice"
    assert document_type("Credit note number will be sent on request") is None
    assert document_type("Invoice number will follow by email") is None


def test_m9_labels_with_a_value_still_count() -> None:
    assert document_type("Credit Note Number: CN-7") == "credit_note"
    assert document_type("Credit Memo # CM-1") == "credit_note"
    assert document_type("Invoice # 42") == "invoice"
    assert document_type("Refers to Invoice: FF-1001") == "credit_note"
