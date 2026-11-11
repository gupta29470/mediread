"""Adversarial safety tests: the engine must refuse unsafe or ungrounded claims."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.explain import ExplanationEngine
from mediread.explain.narrator import apply_narrator
from mediread.explain.safety import (
    allowed_numbers_from_view,
    scan_text,
    validate_narrative,
    validate_section_numbers,
)
from mediread.structured.contract import load_results
from tests.explain_fixtures import make_view

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "artifacts" / "results"
# A report with a broad mix of supported tests, so narrator tests are not
# sensitive to filesystem glob order.
SAMPLE = RESULTS / "4f16a4444054fdfe.results.json"


@pytest.mark.parametrize(
    "text,category",
    [
        ("This means you have diabetes.", "diagnosis_claim"),
        ("The result indicates you have an infection.", "diagnosis_claim"),
        ("You should stop taking your medication.", "treatment_advice"),
        ("We recommend starting a supplement.", "treatment_advice"),
        ("This is an emergency and you should seek medical attention.", "urgency_claim"),
        ("The prognosis is poor.", "prognosis_claim"),
        ("You are perfectly healthy, nothing to worry about.", "false_reassurance"),
    ],
)
def test_unsafe_claims_are_detected(text, category):
    findings = scan_text(text)
    assert any(finding.category == category for finding in findings), findings


@pytest.mark.parametrize(
    "text",
    [
        "This is not a medical diagnosis.",
        "A provider may change treatment based on these results.",
        "MediRead cannot assess how urgent any result is.",
        "Your report lists 9.2 g/dL for haemoglobin.",
    ],
)
def test_neutral_and_negated_text_is_allowed(text):
    assert scan_text(text) == []


def test_invented_number_is_detected():
    findings = validate_section_numbers("Your report lists 9.4 g/dL.", {"9.2"})
    assert findings and findings[0].category == "invented_number"


def test_reported_bound_is_not_invented():
    view = make_view(value="9.2", unit="g/dL", reference="12.0-15.0")
    allowed = allowed_numbers_from_view(view)
    assert validate_section_numbers("Your report lists 9.2 g/dL (12.0-15.0).", allowed) == []


class TamperingNarrator:
    name = "tampering"

    def __init__(self, replacement: str):
        self.replacement = replacement

    def narrate(self, bundle):
        return self.replacement


class SafeNarrator:
    name = "safe"

    def narrate(self, bundle):
        return bundle.education_text + " This is general information only."


@pytest.mark.skipif(not SAMPLE.exists(), reason="result artefacts not generated")
def test_narrator_that_changes_a_number_is_rejected():
    document = ExplanationEngine().explain(load_results(SAMPLE))
    _, results = apply_narrator(document, TamperingNarrator("Your value is 99.9 g/dL."))
    applied = [r for r in results if r.applied]
    assert applied == []
    assert all(not r.applied for r in results)


@pytest.mark.skipif(not SAMPLE.exists(), reason="result artefacts not generated")
def test_narrator_with_unsafe_claim_is_rejected():
    document = ExplanationEngine().explain(load_results(SAMPLE))
    _, results = apply_narrator(
        document, TamperingNarrator("This means you have anaemia.")
    )
    assert all(not r.applied for r in results)


@pytest.mark.skipif(not SAMPLE.exists(), reason="result artefacts not generated")
def test_safe_narrator_is_applied():
    document = ExplanationEngine().explain(load_results(SAMPLE))
    _, results = apply_narrator(document, SafeNarrator())
    assert any(r.applied for r in results)


def test_validate_narrative_rejects_numbers_outside_approved_set():
    findings = validate_narrative(
        "The value 42 is concerning.", allowed_numbers={"9.2"}, approved_text=""
    )
    assert any(f.category == "invented_number" for f in findings)


@pytest.mark.skipif(not RESULTS.exists(), reason="result artefacts not generated")
def test_engine_output_is_clean_on_the_whole_corpus():
    from mediread.explain.safety import validate_document

    findings = []
    for path in sorted(RESULTS.glob("*.results.json")):
        document = ExplanationEngine().explain(load_results(path))
        findings.extend(validate_document(document))
    assert findings == [], findings[:5]


@pytest.mark.skipif(not RESULTS.exists(), reason="result artefacts not generated")
def test_document_carries_disclaimer_and_urgency_notice():
    document = ExplanationEngine().explain(load_results(SAMPLE))
    assert "not a medical diagnosis" in document.disclaimer.lower()
    assert "cannot assess how urgent" in document.urgency_notice.lower()
    payload = document.to_dict()
    assert payload["schema_version"] == "mediread.explanation/1"
    assert payload["mode"] == "deterministic"


@pytest.mark.parametrize(
    "text",
    [
        "MediRead cannot say if you have anemia.",
        "This does not mean you have anemia.",
        "You do not have diabetes.",
        "This is not an emergency.",
        "There is no evidence of a treatment you should start.",
    ],
)
def test_negated_claims_are_not_flagged(text):
    """Regression: an LLM refusal was flagged as a diagnosis claim in M3.1."""
    assert scan_text(text) == []


def test_claim_after_a_contrast_is_still_flagged():
    findings = scan_text("You do not have anaemia, but you have diabetes.")
    assert any(finding.category == "diagnosis_claim" for finding in findings)
