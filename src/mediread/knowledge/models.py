"""Typed view over the knowledge package and the shared name normaliser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SCHEMA_VERSION = "mediread.knowledge/1"
REVIEW_STATUSES = ("draft", "reviewed", "approved")
CLAIM_FIELDS = (
    "what_it_measures",
    "why_it_is_ordered",
    "general_interpretation_high",
    "general_interpretation_low",
    "limitations",
)

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise_name(text: str) -> str:
    """Normalise a test name for exact matching.

    Identical rules to the legacy catalogue (``mediread.explain.knowledge``) so a
    migrated alias keeps the same behaviour: lower-case, ``µ`` → ``u``, every
    run of punctuation becomes a space, whitespace collapsed.
    """
    lowered = (text or "").lower().replace("µ", "u")
    lowered = _PUNCT.sub(" ", lowered)
    return _WS.sub(" ", lowered).strip()


@dataclass(frozen=True)
class Source:
    source_id: str
    title: str
    publisher: str
    source_url: str
    access_date: str
    content_license: str
    source_type: str
    publication_date: str | None = None
    attribution_requirements: str | None = None
    source_notes: str | None = None

    @classmethod
    def from_json(cls, data: dict) -> "Source":
        return cls(
            source_id=data["source_id"],
            title=data["title"],
            publisher=data["publisher"],
            source_url=data["source_url"],
            access_date=data["access_date"],
            content_license=data["content_license"],
            source_type=data["source_type"],
            publication_date=data.get("publication_date"),
            attribution_requirements=data.get("attribution_requirements"),
            source_notes=data.get("source_notes"),
        )

    def to_json(self) -> dict:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "publisher": self.publisher,
            "source_url": self.source_url,
            "publication_date": self.publication_date,
            "access_date": self.access_date,
            "content_license": self.content_license,
            "attribution_requirements": self.attribution_requirements,
            "source_type": self.source_type,
            "source_notes": self.source_notes,
        }


@dataclass(frozen=True)
class KnowledgeTest:
    test_id: str
    canonical_name: str
    category: str
    what_it_measures: str
    why_it_is_ordered: str
    limitations: tuple[str, ...]
    review_status: str
    content_version: int
    general_interpretation_high: str | None = None
    general_interpretation_low: str | None = None
    related_test_ids: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()
    language: str = "en"

    @classmethod
    def from_json(cls, data: dict) -> "KnowledgeTest":
        return cls(
            test_id=data["test_id"],
            canonical_name=data["canonical_name"],
            category=data["category"],
            what_it_measures=data["what_it_measures"],
            why_it_is_ordered=data["why_it_is_ordered"],
            limitations=tuple(data["limitations"]),
            review_status=data["review_status"],
            content_version=int(data["content_version"]),
            general_interpretation_high=data.get("general_interpretation_high"),
            general_interpretation_low=data.get("general_interpretation_low"),
            related_test_ids=tuple(data.get("related_test_ids", ())),
            synonyms=tuple(data.get("synonyms", ())),
            language=data.get("language", "en"),
        )

    def to_json(self) -> dict:
        return {
            "test_id": self.test_id,
            "canonical_name": self.canonical_name,
            "category": self.category,
            "what_it_measures": self.what_it_measures,
            "why_it_is_ordered": self.why_it_is_ordered,
            "general_interpretation_high": self.general_interpretation_high,
            "general_interpretation_low": self.general_interpretation_low,
            "limitations": list(self.limitations),
            "related_test_ids": list(self.related_test_ids),
            "review_status": self.review_status,
            "content_version": self.content_version,
            "language": self.language,
            "synonyms": list(self.synonyms),
        }


@dataclass(frozen=True)
class Alias:
    test_id: str
    alias: str
    alias_type: str = "synonym"
    language: str = "en"
    source: str | None = None

    @property
    def normalized(self) -> str:
        return normalise_name(self.alias)

    @classmethod
    def from_json(cls, data: dict) -> "Alias":
        return cls(
            test_id=data["test_id"],
            alias=data["alias"],
            alias_type=data.get("alias_type", "synonym"),
            language=data.get("language", "en"),
            source=data.get("source"),
        )

    def to_json(self) -> dict:
        return {
            "test_id": self.test_id,
            "alias": self.alias,
            "alias_type": self.alias_type,
            "language": self.language,
            "source": self.source,
        }


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    test_id: str
    source_id: str
    claim_field: str
    supporting_excerpt_or_reference: str
    review_status: str

    @classmethod
    def from_json(cls, data: dict) -> "Evidence":
        return cls(
            evidence_id=data["evidence_id"],
            test_id=data["test_id"],
            source_id=data["source_id"],
            claim_field=data["claim_field"],
            supporting_excerpt_or_reference=data["supporting_excerpt_or_reference"],
            review_status=data["review_status"],
        )

    def to_json(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "test_id": self.test_id,
            "source_id": self.source_id,
            "claim_field": self.claim_field,
            "supporting_excerpt_or_reference": self.supporting_excerpt_or_reference,
            "review_status": self.review_status,
        }


@dataclass(frozen=True)
class Term:
    term_id: str
    technical_term: str
    plain_language_explanation: str
    language: str
    source_id: str

    @classmethod
    def from_json(cls, data: dict) -> "Term":
        return cls(
            term_id=data["term_id"],
            technical_term=data["technical_term"],
            plain_language_explanation=data["plain_language_explanation"],
            language=data["language"],
            source_id=data["source_id"],
        )

    def to_json(self) -> dict:
        return {
            "term_id": self.term_id,
            "technical_term": self.technical_term,
            "plain_language_explanation": self.plain_language_explanation,
            "language": self.language,
            "source_id": self.source_id,
        }


@dataclass
class KnowledgePackage:
    knowledge_version: str
    generated_at: str
    content_hash: str
    sources: list[Source] = field(default_factory=list)
    tests: list[KnowledgeTest] = field(default_factory=list)
    aliases: list[Alias] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    terminology: list[Term] = field(default_factory=list)
    notes: str | None = None

    # ---- derived views -------------------------------------------------
    @property
    def tests_by_id(self) -> dict[str, KnowledgeTest]:
        return {test.test_id: test for test in self.tests}

    @property
    def sources_by_id(self) -> dict[str, Source]:
        return {source.source_id: source for source in self.sources}

    def aliases_for(self, test_id: str) -> tuple[Alias, ...]:
        """Canonical name plus every declared synonym, as alias records."""
        test = self.tests_by_id[test_id]
        canonical = [
            Alias(test_id=test_id, alias=test.canonical_name, alias_type="canonical", language=test.language)
        ]
        declared = [alias for alias in self.aliases if alias.test_id == test_id]
        synonyms = [
            Alias(test_id=test_id, alias=name, alias_type="synonym", language=test.language)
            for name in test.synonyms
        ]
        seen: set[str] = set()
        out: list[Alias] = []
        for alias in canonical + declared + synonyms:
            if alias.normalized in seen:
                continue
            seen.add(alias.normalized)
            out.append(alias)
        return tuple(out)

    def all_aliases(self) -> list[Alias]:
        expanded: list[Alias] = []
        for test in self.tests:
            expanded.extend(self.aliases_for(test.test_id))
        return expanded

    def evidence_for(self, test_id: str) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence if item.test_id == test_id)

    def sources_for(self, test_id: str) -> tuple[Source, ...]:
        source_ids = []
        for item in self.evidence_for(test_id):
            if item.source_id not in source_ids:
                source_ids.append(item.source_id)
        by_id = self.sources_by_id
        return tuple(by_id[source_id] for source_id in source_ids if source_id in by_id)

    def status_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in REVIEW_STATUSES}
        for test in self.tests:
            counts[test.review_status] = counts.get(test.review_status, 0) + 1
        return counts

    def category_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for test in self.tests:
            counts[test.category] = counts.get(test.category, 0) + 1
        return dict(sorted(counts.items()))

    # ---- serialisation -------------------------------------------------
    def to_json(self) -> dict:
        aliases = [alias.to_json() for alias in self.aliases]
        return {
            "schema_version": SCHEMA_VERSION,
            "package": {
                "knowledge_version": self.knowledge_version,
                "generated_at": self.generated_at,
                "content_hash": self.content_hash,
                **({"notes": self.notes} if self.notes else {}),
                "default_language": "en",
            },
            "sources": [source.to_json() for source in self.sources],
            "tests": [test.to_json() for test in self.tests],
            "aliases": aliases,
            "evidence": [item.to_json() for item in self.evidence],
            "terminology": [term.to_json() for term in self.terminology],
        }

    @classmethod
    def from_json(cls, data: dict) -> "KnowledgePackage":
        package = data["package"]
        return cls(
            knowledge_version=package["knowledge_version"],
            generated_at=package["generated_at"],
            content_hash=package["content_hash"],
            notes=package.get("notes"),
            sources=[Source.from_json(item) for item in data["sources"]],
            tests=[KnowledgeTest.from_json(item) for item in data["tests"]],
            aliases=[Alias.from_json(item) for item in data.get("aliases", [])],
            evidence=[Evidence.from_json(item) for item in data.get("evidence", [])],
            terminology=[Term.from_json(item) for item in data.get("terminology", [])],
        )
