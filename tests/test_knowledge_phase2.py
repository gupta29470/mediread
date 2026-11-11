"""Phase 2 acceptance: researched entries, claim-level excerpts, corpus report."""

from __future__ import annotations

from pathlib import Path

import pytest

from mediread.knowledge.package import load_package
from mediread.knowledge.store import KnowledgeStore

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "knowledge" / "mediread-knowledge.json"
DB = REPO / "artifacts" / "knowledge" / "mediread-knowledge.sqlite"

NEW_TESTS = ("crp", "iron_panel", "microalbumin", "rheumatoid_factor", "uric_acid", "vitamin_d")


@pytest.fixture(scope="module")
def package():
    return load_package(PACKAGE)[0]


def test_phase2_entries_exist_and_are_not_approved(package):
    for test_id in NEW_TESTS:
        test = package.tests_by_id[test_id]
        assert test.review_status in ("draft", "reviewed")
        assert test.review_status != "approved"
        assert test.what_it_measures and test.why_it_is_ordered
        assert test.limitations


def test_every_new_entry_quotes_its_source(package):
    for test_id in NEW_TESTS:
        quoted = [
            item for item in package.evidence_for(test_id)
            if "Quoted excerpt" in item.supporting_excerpt_or_reference
        ]
        claims = {item.claim_field for item in quoted}
        assert {"what_it_measures", "why_it_is_ordered"} <= claims, test_id
        for item in quoted:
            assert "https://medlineplus.gov/lab-tests/" in item.supporting_excerpt_or_reference
            assert "Quoted excerpt" in item.supporting_excerpt_or_reference
            # the quote itself must be substantive, not a placeholder
            quote = item.supporting_excerpt_or_reference.split("Quoted excerpt:", 1)[1]
            assert len(quote.strip().strip("\u201c\u201d")) > 80, test_id


def test_sources_have_licence_and_attribution(package):
    for source in package.sources:
        assert source.content_license
        assert source.attribution_requirements
        assert source.access_date


def test_corpus_is_large_enough_for_the_pilot(package):
    assert len(package.tests) >= 80
    assert len(package.sources) >= 18
    assert package.status_counts()["approved"] == 0


def test_new_tests_are_not_reference_ranges(package):
    for test_id in NEW_TESTS:
        test = package.tests_by_id[test_id]
        for text in (test.what_it_measures, test.why_it_is_ordered,
                     test.general_interpretation_high or "", test.general_interpretation_low or ""):
            assert not any(char.isdigit() for char in text) or "2" in text, test_id


def test_reports_are_generated():
    corpus = REPO / "reports" / "knowledge-corpus.md"
    queue = REPO / "reports" / "knowledge-review-queue.md"
    assert corpus.exists() and "Corpus coverage" in corpus.read_text()
    assert queue.exists()
    text = queue.read_text()
    assert "## `vitamin_d`" in text
    assert "draft" in text


def test_built_package_resolves_new_tests(package):
    with KnowledgeStore.open(DB) as store:
        for query, expected in {
            "vitamin d": "vitamin_d",
            "25-OH vitamin D": "vitamin_d",
            "uric acid": "uric_acid",
            "CRP": "crp",
            "rheumatoid factor": "rheumatoid_factor",
            "microalbumin": "microalbumin",
            "serum iron": "iron_panel",
        }.items():
            result = store.lookup(query, include_statuses=("draft",))
            assert result.test_id == expected, query
            # With the production default (approved only) the draft never permits.
            assert store.lookup(query).permitted is False, query
