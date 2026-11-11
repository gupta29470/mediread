"""Permission-gate enforcement: a blocked gate must block its section."""

from __future__ import annotations

import pytest

from mediread.explain.compose import explain_result
from mediread.explain.knowledge import CATALOGUE
from mediread.explain.models import ResultExplanationStatus, SectionKey
from mediread.structured.contract import ResultGates
from tests.explain_fixtures import gate, make_view


def explain(view):
    return explain_result(view, CATALOGUE)


def test_fully_permitted_result_is_explained():
    result = explain(make_view())
    assert result.status is ResultExplanationStatus.EXPLAINED
    assert result.permitted[SectionKey.WHAT_THIS_TEST_MEASURES.value]
    assert result.permitted[SectionKey.COMPARISON_WITH_REFERENCE.value]
    assert "12.0-15.0" in result.section(SectionKey.COMPARISON_WITH_REFERENCE).text


def test_blocked_identify_blocks_education_but_not_the_report_fact():
    view = make_view(gates=ResultGates(gate(True), gate(False), gate(False), gate(False)))
    # identify blocked only
    view = make_view(gates=ResultGates(gate(False), gate(True), gate(True), gate(True)))
    result = explain(view)
    education = result.section(SectionKey.WHAT_THIS_TEST_MEASURES)
    assert education.permitted is False
    assert "not been confirmed" in education.reason
    assert result.section(SectionKey.YOUR_REPORTED_RESULT).permitted is True
    assert result.section(SectionKey.SOURCES).permitted is False
    assert result.section(SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE).permitted is False


def test_blocked_interpret_blocks_interpretation_but_shows_unconfirmed_text():
    view = make_view(gates=ResultGates(gate(True), gate(False), gate(True), gate(True)))
    result = explain(view)
    reported = result.section(SectionKey.YOUR_REPORTED_RESULT)
    assert reported.permitted is True
    assert "not been confirmed" in reported.text
    assert result.section(SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE).permitted is False
    # Comparison must also be withheld even though its own gate was passed.
    assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is False
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is True


def test_blocked_unit_blocks_unit_dependent_comparison():
    view = make_view(
        test_name="MEAN CORPUSCULAR HEMOGLOBIN(MCH)", test_id="mch", unit="pq",
        unit_status="requires_review",
        gates=ResultGates(
            gate(True), gate(True), gate(False, "unit is requires_review"),
            gate(False, "unit is requires_review"),
        ),
    )
    result = explain(view)
    assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is False
    assert "unit" in result.section(SectionKey.COMPARISON_WITH_REFERENCE).reason.lower()
    assert "could not be confirmed" in result.section(SectionKey.YOUR_REPORTED_RESULT).text


def test_blocked_range_blocks_only_the_comparison():
    view = make_view(gates=ResultGates(gate(True), gate(True), gate(True), gate(False)))
    result = explain(view)
    assert result.permitted[SectionKey.WHAT_THIS_TEST_MEASURES.value]
    assert result.permitted[SectionKey.YOUR_REPORTED_RESULT.value]
    assert not result.permitted[SectionKey.COMPARISON_WITH_REFERENCE.value]
    assert result.status is ResultExplanationStatus.PARTIALLY_EXPLAINED


def test_stratified_reference_never_becomes_an_interval():
    view = make_view(
        test_name="EST. GLOMERULAR FILTRATION RATE (eGFR)", test_id="egfr",
        value="112", unit="mL/min/1.73 m2", reference=">= 90 : Normal | 60 - 89 : Mild Decrease",
        low=None, high=None, stratified=True,
        gates=ResultGates(gate(True), gate(True), gate(True), gate(False, "reference is stratified")),
    )
    result = explain(view)
    comparison = result.section(SectionKey.COMPARISON_WITH_REFERENCE)
    assert comparison.permitted is False
    assert "stratified" in (comparison.reason or "").lower()
    # The value itself may still be explained.
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is True


def test_ocr_result_cannot_be_explained_as_verified_fact():
    view = make_view(
        origin="ocr",
        gates=ResultGates(
            gate(False, "test is OCR-derived and must be confirmed"),
            gate(False, "value is OCR-derived and must be confirmed"),
            gate(False, "unit is OCR-derived and must be confirmed"),
            gate(False, "reference is OCR-derived and must be confirmed"),
        ),
    )
    result = explain(view)
    assert result.status is ResultExplanationStatus.WITHHELD
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False
    assert result.section(SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE).permitted is False
    assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is False
    reported = result.section(SectionKey.YOUR_REPORTED_RESULT)
    assert "OCR" in reported.text


def test_missing_reference_has_no_range_interpretation():
    view = make_view(
        test_name="Hb A", test_id="hb_a", value="95.9", unit=None, reference=None,
        low=None, high=None,
        gates=ResultGates(gate(True), gate(True), gate(False), gate(False, "reference is missing")),
    )
    result = explain(view)
    assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is False
    assert "reference" in result.section(SectionKey.COMPARISON_WITH_REFERENCE).reason.lower()
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is True


def test_unknown_test_withholds_education_but_keeps_facts():
    view = make_view(
        test_name="CA-125", test_id=None, value="29.7", unit="U/mL",
        reference="Less than 30.2 U/ml", low=None, high=30.2, operator="<",
    )
    result = explain(view)
    assert result.knowledge_status == "unsupported"
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False
    assert result.section(SectionKey.SOURCES).permitted is False
    assert result.section(SectionKey.YOUR_REPORTED_RESULT).permitted is True
    assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is True
    assert "no approved knowledge entry" in result.section(
        SectionKey.WHAT_THIS_TEST_MEASURES
    ).reason


def test_requires_review_value_still_exposes_permitted_information():
    """A flagged value does not suppress education about a confirmed test."""
    view = make_view(
        value="9.2", value_status="requires_review",
        gates=ResultGates(gate(True), gate(False), gate(True), gate(False)),
    )
    result = explain(view)
    assert result.status is ResultExplanationStatus.PARTIALLY_EXPLAINED
    assert result.section(SectionKey.YOUR_REPORTED_RESULT).permitted is True
    assert "not been confirmed" in result.section(SectionKey.YOUR_REPORTED_RESULT).text
    assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is True
    assert result.section(SectionKey.IMPORTANT_LIMITATIONS).permitted is True


def test_unsupported_test_is_withheld_but_keeps_report_facts():
    view = make_view(
        test_name="SPECIFIC GRAVITY", test_id=None, value="< 1.003", unit="-",
        reference="1.003-1.030", value_status="requires_review",
        parsed_value={"value": "1.003", "bound_operator": "<"},
        gates=ResultGates(gate(True), gate(False), gate(False), gate(False)),
    )
    result = explain(view)
    assert result.status is ResultExplanationStatus.WITHHELD
    assert result.section(SectionKey.YOUR_REPORTED_RESULT).permitted is True
    assert result.section(SectionKey.IMPORTANT_LIMITATIONS).permitted is True


@pytest.mark.parametrize("test_name,test_id,expected", [
    ("HEMOGLOBIN", "hemoglobin", "complete"),
    ("EST. GLOMERULAR FILTRATION RATE (eGFR)", "egfr", "partial"),
    ("CA-125", None, "unsupported"),
])
def test_knowledge_status_is_reported(test_name, test_id, expected):
    view = make_view(test_name=test_name, test_id=test_id)
    assert explain(view).knowledge_status == expected
