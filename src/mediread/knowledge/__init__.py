"""Versioned, reviewable medical knowledge for MediRead.

The package is authored as JSON (``knowledge/mediread-knowledge.json``), validated
against a JSON Schema plus semantic rules, and built into a SQLite package with an
FTS5 index. The runtime looks tests up deterministically; only ``approved``
entries may authorise an explanation, and an ambiguous match never does.

Nothing in this package is a reference range: numerical comparison always uses the
interval printed on the patient's own report.
"""

from __future__ import annotations

from .models import (
    SCHEMA_VERSION,
    REVIEW_STATUSES,
    Alias,
    Evidence,
    KnowledgePackage,
    KnowledgeTest,
    Source,
    Term,
    normalise_name,
)
from .package import KnowledgePackageError, load_package, save_package
from .store import Candidate, KnowledgeStore, LookupResult, lookup_test

__all__ = [
    "SCHEMA_VERSION",
    "REVIEW_STATUSES",
    "Alias",
    "Evidence",
    "KnowledgePackage",
    "KnowledgeTest",
    "Source",
    "Term",
    "normalise_name",
    "KnowledgePackageError",
    "load_package",
    "save_package",
    "Candidate",
    "KnowledgeStore",
    "LookupResult",
    "lookup_test",
]
