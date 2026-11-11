"""Phase 3: the knowledge package feeds the explanation engine and model input."""

from __future__ import annotations

import json

import pytest

from mediread.explain.models import ResultExplanationStatus, SectionKey
from mediread.explain.model_input import SCHEMA_VERSION, serialize_model_input
from mediread.explain.package_provider import (
    AMBIGUOUS_TEMPLATE,
    EVALUATION_STATUSES,
    NOT_APPROVED_TEMPLATE,
    UNSUPPORTED_TEMPLATE,
    PackageProvider,
)
from mediread.explain import ExplanationEngine
from mediread.structured.contract import ExplanationInput, ResultGates
from tests.explain_fixtures import gate, make_view
from tests.knowledge_fixture import build_fixture


def engine_for(tmp_path) -> ExplanationEngine:
    provider = PackageProvider.open(build_fixture(tmp_path))
    return ExplanationEngine(provider=provider)


def input_for(*views) -> ExplanationInput:
    return ExplanationInput(
        contract_version="mediread.explanation-input/1",
        schema_version="mediread.explanation-input/1",
        report_id="rep",
        source_filename="report.pdf",
        generated_at="2026-01-01T00:00:00+00:00",
        results=tuple(views),
    )


def section(explanation, key):
    return explanation.section(key)


def test_approved_entry_explains_with_sources(tmp_path):
    engine = engine_for(tmp_path)
    document = engine.explain(
        input_for(make_view(test_name="HEMOGLOBIN", test_id="hemoglobin")),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    explanation = document.results[0]
    education = section(explanation, SectionKey.WHAT_THIS_TEST_MEASURES)
    sources = section(explanation, SectionKey.SOURCES)
    assert education.permitted and "Hemoglobin" in education.text
    assert sources.permitted and "MedlinePlus" in sources.text
    assert explanation.knowledge_status == "complete"
    assert document.knowledge_version.startswith("2026.11.1+")


def test_draft_entry_is_not_used_in_an_explanation(tmp_path):
    engine = engine_for(tmp_path)
    document = engine.explain(
        input_for(make_view(test_name="CBC panel", test_id=None, unit="-", reference="-",
                            low=None, high=None)),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    explanation = document.results[0]
    education = section(explanation, SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.permitted is False
    assert "not completed review" in (education.reason or "")
    model_input = engine.model_inputs["r1"]
    assert model_input["approved_knowledge"] is None
    from mediread.explain.ambiguity import not_approved_response
    assert model_input["deterministic_response"] == not_approved_response("CBC panel", "draft")


def test_unknown_test_gets_the_deterministic_template(tmp_path):
    engine = engine_for(tmp_path)
    document = engine.explain(
        input_for(make_view(test_name="Neopterin", test_id=None, unit="nmol/L",
                            reference="5-20", low=5, high=20)),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    explanation = document.results[0]
    assert section(explanation, SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False
    assert section(explanation, SectionKey.SOURCES).permitted is False
    model_input = engine.model_inputs["r1"]
    from mediread.explain.ambiguity import unsupported_response
    assert model_input["deterministic_response"] == unsupported_response("Neopterin")
    assert model_input["approved_knowledge"] is None


def test_ambiguous_test_never_explains(tmp_path):
    engine = engine_for(tmp_path)
    document = engine.explain(
        input_for(make_view(test_name="Bilirubin", test_id=None, unit="mg/dL",
                            reference="0.2-1.2", low=0.2, high=1.2)),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    model_input = engine.model_inputs["r1"]
    assert "matches more than one test" in model_input["deterministic_response"]
    assert "Bilirubin" in model_input["deterministic_response"]
    assert model_input["approved_knowledge"] is None
    assert section(document.results[0], SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False


def test_blocked_fields_never_reach_the_model_input(tmp_path):
    engine = engine_for(tmp_path)
    blocked = ResultGates(
        identify_test=gate(True),
        interpret_value=gate(False, "value not confirmed"),
        unit_comparison=gate(False, "unit not confirmed"),
        range_comparison=gate(False, "range not allowed"),
    )
    view = make_view(
        test_name="HEMOGLOBIN", test_id="hemoglobin",
        value="9.2", unit="g/dL", reference="12.0-15.0",
        value_status="requires_review", unit_status="requires_review",
        reference_status="requires_review", gates=blocked,
    )
    engine.explain(input_for(view), generated_at="2026-01-01T00:00:00+00:00")
    model_input = engine.model_inputs["r1"]
    facts = model_input["verified_facts"]
    assert "value_text" not in facts
    assert "unit_text" not in facts
    assert "reference_text" not in facts
    assert model_input["deterministic_comparison"] is None
    assert {"value_text", "unit_text", "reference_text"} <= set(model_input["withheld_fields"])
    # No blocked value can leak through the serialised document either.
    serialized = serialize_model_input(model_input)
    assert "9.2" not in serialized
    assert "12.0-15.0" not in serialized
    assert "g/dL" not in serialized


def test_model_input_is_versioned_and_byte_stable(tmp_path):
    engine = engine_for(tmp_path)
    view = make_view(test_name="HEMOGLOBIN", test_id="hemoglobin")
    engine.explain(input_for(view), generated_at="2026-01-01T00:00:00+00:00")
    first = serialize_model_input(engine.model_inputs["r1"])

    engine.explain(input_for(view), generated_at="2026-01-02T00:00:00+00:00")
    second = serialize_model_input(engine.model_inputs["r1"])
    assert first == second

    payload = json.loads(first)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["approved_knowledge"]["test_id"] == "hemoglobin"
    assert payload["claim_references"]["knowledge_test_id"] == "hemoglobin"
    assert payload["claim_references"]["evidence_ids"]
    assert any("medication" in action for action in payload["prohibited_actions"])
    assert payload["verified_facts"]["value_text"] == "9.2"


def test_reviewed_entry_explains_only_in_evaluation_mode(tmp_path):
    db = build_fixture(tmp_path)
    production = PackageProvider.open(db)
    evaluation = PackageProvider.open(db, include_statuses=EVALUATION_STATUSES)
    assert production.mode == "production" and evaluation.mode == "evaluation"

    # The fixture's approved entry explains in both modes.
    view = make_view(test_name="HEMOGLOBIN", test_id="hemoglobin")
    for provider in (production, evaluation):
        engine = ExplanationEngine(provider=provider)
        document = engine.explain(input_for(view), generated_at="2026-01-01T00:00:00+00:00")
        assert document.results[0].section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is True


def test_engine_with_provider_keeps_withheld_status(tmp_path):
    engine = engine_for(tmp_path)
    document = engine.explain(
        input_for(make_view(test_name="Neopterin", test_id=None, unit="-", reference="-",
                            low=None, high=None)),
        generated_at="2026-01-01T00:00:00+00:00",
    )
    assert document.results[0].status is ResultExplanationStatus.WITHHELD
