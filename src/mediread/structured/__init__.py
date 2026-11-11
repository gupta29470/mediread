"""Structured laboratory-result extraction and validation.

Entry point: :class:`StructuredExtractionPipeline`, which consumes the
``mediread.extraction/1`` contract produced by the ingestion layer and emits
``mediread.results/1`` records with field-level status, confidence and evidence.
"""

from .contract import (
    CONTRACT_VERSION,
    ExplanationInput,
    ResultView,
    build_explanation_input,
    load_document,
    load_results,
)
from .pipeline import StructuredExtractionPipeline, process_path
from .schema import (
    SCHEMA_VERSION,
    ContractError,
    Field,
    FieldStatus,
    LabResult,
    ResultDocument,
)

__all__ = [
    "StructuredExtractionPipeline",
    "process_path",
    "SCHEMA_VERSION",
    "CONTRACT_VERSION",
    "ContractError",
    "Field",
    "FieldStatus",
    "LabResult",
    "ResultDocument",
    "ExplanationInput",
    "ResultView",
    "build_explanation_input",
    "load_document",
    "load_results",
]
