"""Semantic validation and corpus statistics for a knowledge package.

The JSON Schema (see ``schema/knowledge-package.schema.json``) enforces shape. This
module enforces the rules a schema cannot express: referential integrity, alias
conflicts, evidence coverage, licensing metadata and the ban on embedding generic
reference ranges as authoritative values.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .models import CLAIM_FIELDS, REVIEW_STATUSES, normalise_name

# A numeric interval or one-sided bound. The knowledge package may talk about what
# a test measures, never about what counts as "normal" for this patient.
_RANGE = re.compile(
    r"\b\d+(?:\.\d+)?\s*[-\u2013\u2014]\s*\d+(?:\.\d+)?\b"
    r"|\b[<>]\s*=?\s*\d+(?:\.\d+)?\b"
)
_ATTRIBUTION_REQUIRED = ("copyright", "all rights reserved", "cc by", "creative commons")


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_invalid(self) -> None:
        if self.errors:
            raise ValueError("; ".join(self.errors))


def _ids(items, key: str) -> list[str]:
    return [str(item.get(key, "")) for item in items]


def validate_package(data: dict) -> ValidationReport:
    report = ValidationReport()
    errors, warnings = report.errors, report.warnings

    sources = data.get("sources", [])
    tests = data.get("tests", [])
    aliases = data.get("aliases", [])
    evidence = data.get("evidence", [])
    terminology = data.get("terminology", [])

    # --- sources ---------------------------------------------------------
    source_ids = _ids(sources, "source_id")
    if len(set(source_ids)) != len(source_ids):
        errors.append("duplicate source_id in sources")
    by_source = {source.get("source_id"): source for source in sources}
    for source in sources:
        source_id = source.get("source_id")
        licence = (source.get("content_license") or "").strip()
        if not licence:
            errors.append(f"source {source_id}: missing content_license")
        attribution = (source.get("attribution_requirements") or "").strip()
        if not attribution:
            warnings.append(
                f"source {source_id}: no attribution_requirements recorded; confirm the licence "
                "does not require attribution"
            )
        if any(word in licence.lower() for word in _ATTRIBUTION_REQUIRED) and not attribution:
            errors.append(
                f"source {source_id}: licence appears to require attribution but none is recorded"
            )

    # --- tests -----------------------------------------------------------
    test_ids = _ids(tests, "test_id")
    if len(set(test_ids)) != len(test_ids):
        duplicates = [item for item, count in Counter(test_ids).items() if count > 1]
        errors.append(f"duplicate test_id(s): {', '.join(sorted(duplicates))}")
    by_test = {test.get("test_id"): test for test in tests}

    for test in tests:
        test_id = test.get("test_id")
        status = test.get("review_status")
        if status not in REVIEW_STATUSES:
            errors.append(f"{test_id}: invalid review_status {status!r}")
        if int(test.get("content_version", 0)) < 1:
            errors.append(f"{test_id}: content_version must be >= 1")
        for related in test.get("related_test_ids", []):
            if related not in by_test:
                errors.append(f"{test_id}: related_test_id {related!r} does not exist")
        # Generic ranges must never be stored as authoritative comparison values.
        for field_name in ("general_interpretation_high", "general_interpretation_low"):
            text = test.get(field_name)
            if text and _RANGE.search(text):
                errors.append(
                    f"{test_id}.{field_name}: contains a numeric range or bound; the knowledge "
                    "package must not carry reference intervals"
                )
        for field_name in ("what_it_measures", "why_it_is_ordered"):
            text = test.get(field_name) or ""
            if _RANGE.search(text):
                warnings.append(
                    f"{test_id}.{field_name}: mentions a numeric range/bound; confirm it is not a "
                    "reference interval"
                )

    # --- aliases ---------------------------------------------------------
    seen_alias: dict[tuple[str, str], str] = {}
    alias_to_tests: dict[str, set[str]] = {}
    for alias in aliases:
        test_id = alias.get("test_id")
        raw = alias.get("alias") or ""
        if test_id not in by_test:
            errors.append(f"alias {raw!r}: unknown test_id {test_id!r}")
            continue
        key = (test_id, normalise_name(raw))
        if key in seen_alias:
            errors.append(f"{test_id}: duplicate alias {raw!r}")
        seen_alias[key] = raw
        alias_to_tests.setdefault(normalise_name(raw), set()).add(test_id)
    for test in tests:
        canonical = test.get("canonical_name") or ""
        test_id = test.get("test_id")
        # A canonical name is a matchable alias, but it is not a "duplicate" when
        # the same string is also listed as a synonym.
        alias_to_tests.setdefault(normalise_name(canonical), set()).add(test_id)
        for synonym in test.get("synonyms", []):
            test_id = test.get("test_id")
            key = (test_id, normalise_name(synonym))
            if key in seen_alias:
                errors.append(f"{test_id}: duplicate alias {synonym!r} (also declared elsewhere)")
            seen_alias[key] = synonym
            alias_to_tests.setdefault(normalise_name(synonym), set()).add(test_id)

    ambiguous_aliases = {
        alias: sorted(ids) for alias, ids in alias_to_tests.items() if len(ids) > 1
    }
    for alias, ids in sorted(ambiguous_aliases.items()):
        warnings.append(f"ambiguous alias {alias!r} maps to {', '.join(ids)}")

    # --- evidence --------------------------------------------------------
    evidence_ids = _ids(evidence, "evidence_id")
    if len(set(evidence_ids)) != len(evidence_ids):
        errors.append("duplicate evidence_id in evidence")
    covered: dict[str, set[str]] = {}
    for item in evidence:
        test_id = item.get("test_id")
        source_id = item.get("source_id")
        claim = item.get("claim_field")
        if test_id not in by_test:
            errors.append(f"evidence {item.get('evidence_id')}: unknown test_id {test_id!r}")
            continue
        if source_id not in by_source:
            errors.append(
                f"evidence {item.get('evidence_id')}: source_id {source_id!r} does not exist"
            )
        if claim not in CLAIM_FIELDS:
            errors.append(f"evidence {item.get('evidence_id')}: invalid claim_field {claim!r}")
        if item.get("review_status") not in REVIEW_STATUSES:
            errors.append(
                f"evidence {item.get('evidence_id')}: invalid review_status "
                f"{item.get('review_status')!r}"
            )
        covered.setdefault(test_id, set()).add(claim)

    for test in tests:
        test_id = test.get("test_id")
        claims = covered.get(test_id, set())
        for required in ("what_it_measures", "why_it_is_ordered"):
            if required not in claims:
                errors.append(f"{test_id}: no evidence for {required}")
        if test.get("general_interpretation_high") and "general_interpretation_high" not in claims:
            errors.append(f"{test_id}: general_interpretation_high has no evidence")
        if test.get("general_interpretation_low") and "general_interpretation_low" not in claims:
            errors.append(f"{test_id}: general_interpretation_low has no evidence")

    # --- terminology -----------------------------------------------------
    for term in terminology:
        if term.get("source_id") not in by_source:
            errors.append(f"term {term.get('term_id')}: unknown source_id {term.get('source_id')!r}")

    # --- statistics ------------------------------------------------------
    status_counts = Counter(test.get("review_status") for test in tests)
    category_counts = Counter(test.get("category") for test in tests)
    canonical_count = sum(1 for test in tests if test.get("canonical_name"))
    report.stats = {
        "tests": len(tests),
        "sources": len(sources),
        "aliases": len(seen_alias) + canonical_count,
        "evidence": len(evidence),
        "terminology": len(terminology),
        "by_status": {status: status_counts.get(status, 0) for status in REVIEW_STATUSES},
        "by_category": dict(sorted(category_counts.items())),
        "ambiguous_aliases": {alias: ids for alias, ids in sorted(ambiguous_aliases.items())},
        "tests_with_high_note": sum(1 for test in tests if test.get("general_interpretation_high")),
        "tests_with_low_note": sum(1 for test in tests if test.get("general_interpretation_low")),
        "sources_missing_attribution": [
            source.get("source_id")
            for source in sources
            if not (source.get("attribution_requirements") or "").strip()
        ],
    }
    return report
