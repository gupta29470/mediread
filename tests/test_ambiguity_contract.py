"""Deterministic ambiguity/unsupported responses (Task 1 regression suite)."""

from __future__ import annotations

from mediread.explain import ExplanationEngine
from mediread.explain.ambiguity import not_approved_response, unsupported_response
from mediread.explain.models import SectionKey
from mediread.explain.package_provider import PackageProvider
from mediread.structured.contract import ExplanationInput

from tests.explain_fixtures import make_view
from tests.knowledge_fixture import build_fixture


def engine_for(tmp_path) -> tuple[ExplanationEngine, PackageProvider]:
    provider = PackageProvider.open(build_fixture(tmp_path))
    return ExplanationEngine(provider=provider), provider


def input_for(view) -> ExplanationInput:
    return ExplanationInput(
        contract_version="mediread.explanation-input/1",
        schema_version="mediread.explanation-input/1",
        report_id="rep",
        source_filename="report.pdf",
        generated_at="2026-01-01T00:00:00+00:00",
        results=(view,),
    )


def test_unknown_test_explains_that_it_is_not_covered(tmp_path):
    engine, provider = engine_for(tmp_path)
    lookup = provider.lookup(None, "Neopterin")
    assert lookup.permitted is False if hasattr(lookup, "permitted") else lookup.entry is None
    assert lookup.entry is None
    assert lookup.template == unsupported_response("Neopterin")
    assert "not currently covered" in lookup.template

    document = engine.explain(input_for(make_view(test_name="Neopterin", test_id=None)),
                              generated_at="2026-01-01T00:00:00+00:00")
    education = document.results[0].section(SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.permitted is False
    assert education.reason == lookup.template


def test_draft_knowledge_is_refused_with_its_status(tmp_path):
    engine, provider = engine_for(tmp_path)
    lookup = provider.lookup(None, "CBC panel")
    assert lookup.entry is None
    assert lookup.template == not_approved_response("CBC panel", "draft")
    assert "not completed review (status: draft)" in lookup.template

    document = engine.explain(
        input_for(make_view(test_name="CBC panel", test_id=None, unit="-", reference="-")),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    education = document.results[0].section(SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.reason == lookup.template


def test_ambiguous_name_names_candidates_and_asks_for_clarification(tmp_path):
    engine, provider = engine_for(tmp_path)
    lookup = provider.lookup(None, "FBC")  # shared alias in the fixture
    assert lookup.entry is None
    assert lookup.ambiguous is True
    assert len(lookup.ambiguous_names) == 2
    text = lookup.template
    assert "matches more than one test" in text
    assert "Complete blood count" in text and "differential" in text
    assert "cannot safely choose" in text
    assert "original report" in text

    document = engine.explain(
        input_for(make_view(test_name="FBC", test_id=None, unit="-", reference="-")),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    explanation = document.results[0]
    education = explanation.section(SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.permitted is False
    assert education.reason == text
    # the ambiguity decision came from retrieval, not the model
    model_input = engine.model_inputs["r1"]
    assert model_input["approved_knowledge"] is None
    assert model_input["deterministic_response"] == text
    # No interpretable facts reach a model for an ambiguous result.
    assert model_input["mode"] == "deterministic_only"
    assert model_input["verified_facts"] == {}
    assert model_input["deterministic_comparison"] is None


def test_approved_exact_match_is_explained_and_has_no_template(tmp_path):
    engine, provider = engine_for(tmp_path)
    lookup = provider.lookup("hemoglobin", "HEMOGLOBIN")
    assert lookup.entry is not None
    assert lookup.template is None
    assert lookup.review_status == "approved"

    document = engine.explain(input_for(make_view(test_name="HEMOGLOBIN", test_id="hemoglobin")),
                              generated_at="2026-01-01T00:00:00+00:00")
    education = document.results[0].section(SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.permitted is True
    assert "Hemoglobin" in education.text
    assert engine.model_inputs["r1"]["approved_knowledge"]["test_id"] == "hemoglobin"


def test_conflicting_aliases_are_never_resolved_by_guessing(tmp_path):
    _, provider = engine_for(tmp_path)
    first = provider.lookup(None, "fbc")
    second = provider.lookup(None, "FBC")
    assert first.ambiguous is True and second.ambiguous is True
    assert set(first.ambiguous_names) == set(second.ambiguous_names)
    assert first.entry is None and second.entry is None
