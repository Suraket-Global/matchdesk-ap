"""Extraction adapters (fake, local text PDF; hosted provider deferred) and verification gates."""

from matchdesk.extraction.provider import (
    Extracted,
    ExtractionNotConfiguredError,
    ExtractionPermanentError,
    ExtractionTransientError,
    Extractor,
    FakeExtractor,
    extractor_from_settings,
    verification_gates,
)

__all__ = [
    "Extracted",
    "ExtractionNotConfiguredError",
    "ExtractionPermanentError",
    "ExtractionTransientError",
    "Extractor",
    "FakeExtractor",
    "extractor_from_settings",
    "verification_gates",
]
