"""One-off migration: legacy bundled catalogue → versioned knowledge package.

The legacy catalogue (``mediread.explain.knowledge``) already carries careful
MedlinePlus-sourced summaries and a licence analysis. This module turns it into the
package format instead of re-authoring the text.

Two honest downgrades:

* ``review_status`` becomes ``draft`` for every entry. The legacy ``status`` field
  meant "source coverage" (complete/partial), not independent review, and no
  qualified reviewer has approved this content.
* evidence records point at the source page (title, URL, access date), not at a
  verbatim excerpt, because the legacy catalogue stores summaries rather than
  quotations. The record says so explicitly.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from mediread.explain.knowledge.entries import ENTRIES
from mediread.explain.knowledge.sources import SOURCES

from .models import Evidence, KnowledgePackage, KnowledgeTest, Source

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG.sub("_", text.lower()).strip("_")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_from_legacy(*, knowledge_version: str = "2026.11.1", generated_at: str | None = None) -> KnowledgePackage:
    sources = [
        Source(
            source_id=source.source_id,
            title=source.title,
            publisher=source.organization,
            source_url=source.url,
            access_date=source.accessed,
            content_license=source.licence,
            source_type="government",
            publication_date=None,
            attribution_requirements=source.licence_note,
            source_notes=source.licence_note,
        )
        for source in SOURCES.values()
    ]

    tests: list[KnowledgeTest] = []
    evidence: list[Evidence] = []
    for entry in ENTRIES:
        tests.append(
            KnowledgeTest(
                test_id=entry.test_id,
                canonical_name=entry.canonical_name,
                category=entry.category,
                what_it_measures=entry.measures,
                why_it_is_ordered=entry.why_ordered,
                general_interpretation_high=entry.high_note,
                general_interpretation_low=entry.low_note,
                limitations=tuple(entry.limitations),
                related_test_ids=(),
                synonyms=tuple(entry.aliases),
                review_status="draft",
                content_version=1,
            )
        )
        claim_fields = ["what_it_measures", "why_it_is_ordered", "limitations"]
        if entry.high_note:
            claim_fields.append("general_interpretation_high")
        if entry.low_note:
            claim_fields.append("general_interpretation_low")
        for source_id in entry.sources:
            source = SOURCES[source_id]
            for claim_field in claim_fields:
                evidence.append(
                    Evidence(
                        evidence_id=f"{entry.test_id}__{claim_field}__{_slug(source_id)}",
                        test_id=entry.test_id,
                        source_id=source_id,
                        claim_field=claim_field,
                        supporting_excerpt_or_reference=(
                            f"{source.title} — {source.url} (accessed {source.accessed}). "
                            "Source-level reference from the pilot catalogue; the summary is "
                            "original wording, not a verbatim excerpt."
                        ),
                        review_status="draft",
                    )
                )

    return KnowledgePackage(
        knowledge_version=knowledge_version,
        generated_at=generated_at or _now(),
        content_hash="0" * 64,  # recomputed by save_package
        sources=sources,
        tests=tests,
        aliases=[],
        evidence=evidence,
        terminology=[],
        notes=(
            "Migrated from the legacy bundled catalogue (MedlinePlus-sourced summaries, "
            "licence analysis in src/mediread/explain/knowledge/sources.py). Every entry is "
            "draft: source coverage was recorded during the pilot, but no independent "
            "clinical review has approved it."
        ),
    )
