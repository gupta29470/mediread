"""Bundled, versioned medical knowledge with source provenance."""

from .catalogue import CATALOGUE, KnowledgeCatalogue, LookupResult, normalise_name
from .entries import ENTRIES, KnowledgeEntry
from .sources import (
    ATTRIBUTION,
    EXCLUDED_SOURCES,
    KNOWLEDGE_VERSION,
    SOURCES,
    KnowledgeSource,
    get_source,
)

__all__ = [
    "CATALOGUE",
    "KnowledgeCatalogue",
    "LookupResult",
    "normalise_name",
    "ENTRIES",
    "KnowledgeEntry",
    "ATTRIBUTION",
    "EXCLUDED_SOURCES",
    "KNOWLEDGE_VERSION",
    "SOURCES",
    "KnowledgeSource",
    "get_source",
]
