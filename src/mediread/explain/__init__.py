"""Medical explanation engine (Milestone 3).

Consumes ``mediread.explanation-input/1`` and produces
``mediread.explanation/1``: sectioned, permission-gated, source-grounded
educational explanations. Deterministic by default; no model is bundled.
"""

from .knowledge.catalogue import CATALOGUE, KnowledgeCatalogue
from .models import (
    SCHEMA_VERSION,
    Comparison,
    ComparisonState,
    ExplanationDocument,
    ResultExplanation,
    ResultExplanationStatus,
    Section,
    SectionKey,
    SectionKind,
)
from .pipeline import ExplanationEngine

__all__ = [
    "CATALOGUE",
    "KnowledgeCatalogue",
    "SCHEMA_VERSION",
    "Comparison",
    "ComparisonState",
    "ExplanationDocument",
    "ResultExplanation",
    "ResultExplanationStatus",
    "Section",
    "SectionKey",
    "SectionKind",
    "ExplanationEngine",
]
