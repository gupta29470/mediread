"""Knowledge provider backed by the built knowledge package.

It exposes the same small surface the composer already uses (``lookup``,
``sources_for``, ``version``) so the deterministic engine can run against either
the legacy catalogue or the package.

The one behaviour that matters for safety: **only an approved, unambiguous entry is
permitted**. A draft entry, an ambiguous name and an unknown name all produce
``entry=None`` with a specific reason, so the education section is withheld and no
number is ever composed from unreviewed knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..knowledge.store import KnowledgeStore
from .ambiguity import (
    ambiguity_response,
    not_approved_response,
    unsupported_response,
)

# Kept as module constants for callers that import them by name; the live text is
# built by :mod:`mediread.explain.ambiguity` with the query and candidates included.
UNSUPPORTED_TEMPLATE = unsupported_response("this test")
AMBIGUOUS_TEMPLATE = ambiguity_response(
    "this test", ["one test", "another test"]
)
NOT_APPROVED_TEMPLATE = not_approved_response("this test", "draft")

_GENERAL_NOTE = (
    "MediRead explains the general purpose of this test; the comparison uses the "
    "reference interval printed on your own report."
)


@dataclass(frozen=True)
class PackageEntry:
    """Legacy-compatible view of a knowledge entry (the composer's attribute set)."""

    test_id: str
    canonical_name: str
    category: str
    measures: str
    why_ordered: str
    general_note: str
    kind: str
    qualitative_note: str | None
    low_note: str | None
    high_note: str | None
    limitations: tuple[str, ...]
    sources: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class PackageLookup:
    entry: PackageEntry | None
    match: str
    reason: str
    review_status: str | None = None
    ambiguous: bool = False
    test_id: str | None = None
    query: str = ""
    ambiguous_names: tuple[str, ...] = ()

    @property
    def template(self) -> str | None:
        """The deterministic response to use when no explanation is permitted."""
        if self.entry is not None:
            return None
        if self.ambiguous:
            return ambiguity_response(self.query, self.ambiguous_names)
        if self.review_status and self.review_status != "approved":
            return not_approved_response(self.query, self.review_status)
        return unsupported_response(self.query)


#: Statuses a production engine may explain from.
PRODUCTION_STATUSES = ("approved",)
#: Evaluation-only statuses: reviewed-but-not-approved content may be used to build
#: and test the pipeline. Never use this list in a shipped app.
EVALUATION_STATUSES = ("reviewed", "approved")


class PackageProvider:
    """Knowledge lookup over a built SQLite package.

    ``include_statuses`` is the enforcement point. Production uses the default
    (``approved`` only); ``EVALUATION_STATUSES`` exists for dataset generation and
    model evaluation before clinical approval and must not be used in production.
    """

    def __init__(self, store: KnowledgeStore, *, include_statuses: tuple[str, ...] = PRODUCTION_STATUSES) -> None:
        self.store = store
        self.include_statuses = tuple(include_statuses)
        self._errors: tuple[str, ...] = ()

    @classmethod
    def open(cls, db_path, *, include_statuses: tuple[str, ...] = PRODUCTION_STATUSES) -> "PackageProvider":
        return cls(KnowledgeStore.open(db_path), include_statuses=include_statuses)

    @property
    def mode(self) -> str:
        return "production" if self.include_statuses == PRODUCTION_STATUSES else "evaluation"

    @property
    def version(self) -> str:
        metadata = self.store.metadata
        return f"{metadata.get('knowledge_version', 'unknown')}+{metadata.get('content_hash', '')[:12]}"

    @property
    def errors(self) -> tuple[str, ...]:
        return self._errors

    def lookup(self, test_id: str | None, test_name: str, section: str | None = None) -> PackageLookup:
        query = (test_name or "").strip() or (test_id or "").strip()
        if not query:
            return PackageLookup(None, "unsupported", "no test name", test_id=test_id)
        result = self.store.lookup(query, include_statuses=self.include_statuses)
        if result.permitted and result.test_id:
            entry = self.store.get(result.test_id)
            if entry is None:
                return PackageLookup(None, "unsupported", "entry vanished after lookup")
            source_ids = tuple(source["source_id"] for source in entry["sources"])
            return PackageLookup(
                self._entry(entry, source_ids),
                result.match_type,
                result.rationale,
                review_status=entry["review_status"],
                test_id=entry["test_id"],
            )
        if result.ambiguous:
            names = tuple(candidate.canonical_name for candidate in result.candidates)
            text = ambiguity_response(query, names)
            return PackageLookup(
                None, "ambiguous", text, ambiguous=True, query=query, ambiguous_names=names,
            )
        if result.test_id:
            # Found, but its review status is not approved.
            return PackageLookup(
                None, result.match_type,
                not_approved_response(query, result.review_status or "draft"),
                review_status=result.review_status, test_id=result.test_id, query=query,
            )
        return PackageLookup(None, "unsupported", unsupported_response(query), query=query)

    def _entry(self, row: dict, source_ids: tuple[str, ...]) -> PackageEntry:
        return PackageEntry(
            test_id=row["test_id"],
            canonical_name=row["canonical_name"],
            category=row["category"],
            measures=row["what_it_measures"],
            why_ordered=row["why_it_is_ordered"],
            general_note=_GENERAL_NOTE,
            kind="numeric",
            qualitative_note=None,
            low_note=row["general_interpretation_low"],
            high_note=row["general_interpretation_high"],
            limitations=tuple(row["limitations"]),
            sources=source_ids,
            status="complete" if row["review_status"] == "approved" else "partial",
        )

    def evidence_for(self, test_id: str) -> tuple[str, ...]:
        """Evidence rows backing this entry, for claim traceability."""
        rows = self.store._connection.execute(
            "SELECT evidence_id FROM evidence WHERE test_id = ? ORDER BY evidence_id",
            (test_id,),
        ).fetchall()
        return tuple(row["evidence_id"] for row in rows)

    def sources_for(self, entry: PackageEntry) -> list[dict[str, str]]:
        rows = self.store._connection.execute(
            "SELECT source_id, title, publisher, source_url, access_date, content_license "
            "FROM sources WHERE source_id IN (%s) ORDER BY source_id"
            % ",".join("?" * len(entry.sources)),
            entry.sources,
        ).fetchall() if entry.sources else []
        return [
            {
                "source_id": row["source_id"],
                "title": row["title"],
                "organization": row["publisher"],
                "url": row["source_url"],
                "accessed": row["access_date"],
                "licence": row["content_license"],
            }
            for row in rows
        ]
