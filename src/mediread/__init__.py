"""MediRead — privacy-first laboratory report understanding.

Phase 1 scope: document ingestion (inspection, text extraction, rendering, OCR)
with page-level provenance. The package is import-safe without any OCR engine
installed; engines are loaded lazily through :mod:`mediread.ocr.registry`.
"""

__version__ = "0.1.0"
