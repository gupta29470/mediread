"""Lookup contract: exact id, exact alias, FTS5, ambiguity and status gating."""

from __future__ import annotations

from mediread.knowledge.store import KnowledgeStore

from .knowledge_fixture import build_fixture

APPROVED = ("approved",)
ALL = ("draft", "reviewed", "approved")


def open_store(tmp_path) -> KnowledgeStore:
    return KnowledgeStore.open(build_fixture(tmp_path))


def test_exact_canonical_id(tmp_path):
    with open_store(tmp_path) as store:
        result = store.lookup("hemoglobin")
    assert result.match_type == "canonical_id"
    assert result.test_id == "hemoglobin"
    assert result.permitted is True
    assert result.ambiguous is False
    assert result.sources and result.sources[0]["source_id"] == "src_nlm"


def test_exact_alias_is_case_and_punctuation_insensitive(tmp_path):
    with open_store(tmp_path) as store:
        for query in ("Haemoglobin", "haemoglobin", "Hb", "HAEMOGLOBIN"):
            result = store.lookup(query)
            assert result.match_type == "alias", query
            assert result.test_id == "hemoglobin"
            assert result.permitted is True


def test_unknown_test_is_unsupported_and_never_permitted(tmp_path):
    with open_store(tmp_path) as store:
        result = store.lookup("mystery marker")
    assert result.match_type == "unsupported"
    assert result.permitted is False
    assert result.test_id is None


def test_two_distinct_tests_are_not_merged(tmp_path):
    with open_store(tmp_path) as store:
        total = store.lookup("total bilirubin")
        direct = store.lookup("direct bilirubin")
        ambiguous = store.lookup("bilirubin")
    assert total.test_id == "bilirubin_total"
    assert direct.test_id == "bilirubin_direct"
    assert total.test_id != direct.test_id
    # "bilirubin" alone is a lexical candidate of both: no automatic explanation.
    assert ambiguous.match_type == "ambiguous"
    assert ambiguous.permitted is False
    assert {"bilirubin_total", "bilirubin_direct"} <= {item.test_id for item in ambiguous.candidates}


def test_shared_alias_is_ambiguous(tmp_path):
    with open_store(tmp_path) as store:
        result = store.lookup("fbc")
    assert result.match_type == "ambiguous"
    assert result.ambiguous is True
    assert result.permitted is False
    assert len(result.candidates) == 2


def test_fts5_single_candidate_is_permitted(tmp_path):
    with open_store(tmp_path) as store:
        result = store.lookup("hemoglobin hemogram")
    assert result.match_type == "fts5"
    assert result.test_id == "hemoglobin"
    assert result.permitted is True
    assert result.candidates[0].score is not None


def test_fts5_two_candidates_are_ambiguous(tmp_path):
    with open_store(tmp_path) as store:
        result = store.lookup("cbc hemogram")
    assert result.match_type == "ambiguous"
    assert result.permitted is False
    assert len(result.candidates) >= 2


def test_draft_entry_is_found_but_not_permitted(tmp_path):
    with open_store(tmp_path) as store:
        gated = store.lookup("CBC panel", include_statuses=APPROVED)
        allowed = store.lookup("CBC panel", include_statuses=ALL)
    assert gated.test_id == "cbc_with_diff"
    assert gated.review_status == "draft"
    assert gated.permitted is False
    assert "not permitted" in gated.rationale
    assert allowed.permitted is True


def test_get_returns_entry_with_sources_and_aliases(tmp_path):
    with open_store(tmp_path) as store:
        entry = store.get("hemoglobin")
    assert entry["canonical_name"] == "Hemoglobin"
    assert "Haemoglobin" in entry["aliases"]
    assert entry["sources"][0]["title"].startswith("MedlinePlus")
    assert entry["review_status"] == "approved"
