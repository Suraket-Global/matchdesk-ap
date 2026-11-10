"""Extraction adapters (fake only in B1) and verification gates."""

from matchdesk.extraction.provider import (
    Extracted,
    ExtractionPermanentError,
    ExtractionTransientError,
    Extractor,
    FakeExtractor,
    verification_gates,
)

__all__ = [
    "Extracted",
    "ExtractionPermanentError",
    "ExtractionTransientError",
    "Extractor",
    "FakeExtractor",
    "verification_gates",
]
