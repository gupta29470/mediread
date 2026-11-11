"""Typed exceptions. Callers can distinguish recoverable page issues from fatal ones."""

from __future__ import annotations


class MediReadError(Exception):
    """Base class for all domain errors."""


class UnsupportedInputError(MediReadError):
    """Input is not a PDF/image we can process."""


class DocumentLoadError(MediReadError):
    """The PDF could not be opened (corrupt, encrypted, wrong password)."""


class PageProcessingError(MediReadError):
    """A single page failed; the document pipeline records it and continues."""

    def __init__(self, page_number: int, message: str) -> None:
        super().__init__(f"page {page_number}: {message}")
        self.page_number = page_number


class OcrUnavailableError(MediReadError):
    """The requested OCR engine is not installed or could not initialise."""


class OcrInferenceError(MediReadError):
    """The OCR engine is installed but failed on this image."""


class GroundTruthError(MediReadError):
    """Ground-truth data is missing or malformed."""
