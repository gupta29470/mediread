"""Deterministic numerical interpretation: every boundary is explicit."""

from __future__ import annotations

import pytest

from mediread.explain.interpret import compare_result
from mediread.explain.models import ComparisonState
from mediread.structured.contract import (
    EvidenceView,
    FieldView,
    ReferenceBounds,
    ResultGates,
    ResultView,
    UsageGate,
)


def _gate(ok: bool) -> UsageGate:
    return UsageGate(ok, () if ok else ("x",), None if ok else "blocked")


def _field(text, status="verified", *, normalized=None, parsed=None, origin="embedded"):
    return FieldView(
        text=text,
        status=status,
        confidence=1.0,
        normalized=normalized,
        parsed=parsed,
        reasons=(),
        alternatives=(),
        evidence=EvidenceView(1, (0.0, 0.0, 1.0, 1.0), text or "", origin, None),
    )


def make_view(
    *,
    value="9.2",
    unit="g/dL",
    reference="12.0-15.0",
    low=12.0,
    high=15.0,
    low_inclusive=True,
    high_inclusive=True,
    operator=None,
    stratified=False,
    value_kind="numeric",
    value_number=None,
    parsed_value=None,
    reference_parsed=None,
    value_status="verified",
    reference_status="verified",
    unit_status="verified",
    gates=None,
    test_name="HEMOGLOBIN",
) -> ResultView:
    bounds = ReferenceBounds(
        low=low,
        high=high,
        low_inclusive=low_inclusive,
        high_inclusive=high_inclusive,
        operator=operator,
        stratified=stratified,
    )
    if reference_parsed is None:
        reference_parsed = {
            "text": reference,
            "low": low,
            "high": high,
            "low_inclusive": low_inclusive,
            "high_inclusive": high_inclusive,
            "operator": operator,
            "stratified": stratified,
        }
    return ResultView(
        result_id="r1",
        report_id="rep",
        page=1,
        section="CBC / Hemogram",
        test_name=test_name,
        test_id="hemoglobin",
        value_text=value,
        value_number=value_number if value_number is not None else value,
        value_kind=value_kind,
        unit_text=unit,
        unit_canonical=unit,
        reference_text=reference,
        reference_bounds=bounds,
        qualitative_text=value if value_kind == "qualitative" else None,
        status="verified",
        confidence=0.99,
        fields={
            "test": _field(test_name),
            "value": _field(value, value_status, parsed=parsed_value),
            "unit": _field(unit, unit_status),
            "reference": _field(reference, reference_status, parsed=reference_parsed),
        },
        warnings=(),
        row_evidence=None,
        gates=gates or ResultGates(_gate(True), _gate(True), _gate(True), _gate(True)),
    )


def test_value_inside_range():
    assert compare_result(make_view(value="13.5")).state is ComparisonState.WITHIN_RANGE


def test_value_below_range():
    assert compare_result(make_view(value="9.2")).state is ComparisonState.BELOW_RANGE


def test_value_above_range():
    assert compare_result(make_view(value="16.1")).state is ComparisonState.ABOVE_RANGE


def test_value_exactly_on_inclusive_lower_bound_is_within():
    assert compare_result(make_view(value="12.0")).state is ComparisonState.WITHIN_RANGE


def test_value_exactly_on_inclusive_upper_bound_is_within():
    assert compare_result(make_view(value="15.0")).state is ComparisonState.WITHIN_RANGE


def test_value_exactly_on_exclusive_lower_bound_is_below():
    view = make_view(value="12.0", low_inclusive=False)
    assert compare_result(view).state is ComparisonState.BELOW_RANGE


def test_value_exactly_on_exclusive_upper_bound_is_above():
    view = make_view(value="15.0", high_inclusive=False)
    assert compare_result(view).state is ComparisonState.ABOVE_RANGE


def test_decimal_precision_is_not_lost():
    view = make_view(value="0.58", low=0.3, high=1.2, reference="0.3-1.2")
    assert compare_result(view).state is ComparisonState.WITHIN_RANGE
    view = make_view(value="0.13", low=None, high=0.3, reference="< 0.3", operator="<")
    assert compare_result(view).state is ComparisonState.SATISFIES_ONE_SIDED


def test_one_sided_upper_bound():
    satisfied = make_view(value="13.83", low=None, high=38.0, reference="< 38", operator="<")
    assert compare_result(satisfied).state is ComparisonState.SATISFIES_ONE_SIDED
    violated = make_view(value="40", low=None, high=38.0, reference="< 38", operator="<")
    assert compare_result(violated).state is ComparisonState.VIOLATES_ONE_SIDED


def test_one_sided_lower_bound():
    satisfied = make_view(value="112", low=90.0, high=None, reference="> 90", operator=">")
    assert compare_result(satisfied).state is ComparisonState.SATISFIES_ONE_SIDED
    violated = make_view(value="80", low=90.0, high=None, reference="> 90", operator=">")
    assert compare_result(violated).state is ComparisonState.VIOLATES_ONE_SIDED


def test_one_sided_boundary_is_exclusive():
    at_bound = make_view(value="38", low=None, high=38.0, reference="< 38", operator="<")
    assert compare_result(at_bound).state is ComparisonState.VIOLATES_ONE_SIDED


def test_stratified_reference_is_never_an_interval():
    view = make_view(value="112", low=None, high=None, stratified=True, reference=">=90: Normal")
    assert compare_result(view).state is ComparisonState.NOT_COMPARABLE_STRATIFIED


def test_missing_reference():
    view = make_view(value="9.2", low=None, high=None, reference=None)
    assert compare_result(view).state is ComparisonState.NOT_COMPARABLE_MISSING_REFERENCE


def test_reported_bound_value_is_not_an_interval_comparison():
    view = make_view(
        value="< 1.003", parsed_value={"value": "1.003", "bound_operator": "<"},
        low=1.003, high=1.03, reference="1.003-1.030",
    )
    assert compare_result(view).state is ComparisonState.NOT_COMPARABLE_VALUE


def test_qualitative_match():
    view = make_view(
        value="PALE YELLOW", unit="-", reference="Pale Yellow", value_kind="qualitative",
        low=None, high=None,
    )
    assert compare_result(view).state is ComparisonState.MATCHES_QUALITATIVE_REFERENCE


def test_qualitative_difference():
    view = make_view(
        value="PRESENT", unit="-", reference="Absent", value_kind="qualitative",
        low=None, high=None,
    )
    assert compare_result(view).state is ComparisonState.DIFFERS_FROM_QUALITATIVE_REFERENCE


def test_qualitative_against_numeric_reference_is_not_comparable():
    view = make_view(
        value="Normal", unit="mg/dL", reference="<=0.2", value_kind="qualitative",
        low=None, high=0.2, operator="<=",
    )
    assert compare_result(view).state is ComparisonState.NOT_COMPARABLE_VALUE


def test_blocked_gate_prevents_comparison():
    view = make_view(
        gates=ResultGates(_gate(True), _gate(True), _gate(True), _gate(False))
    )
    assert compare_result(view).state is ComparisonState.BLOCKED_BY_GATE


@pytest.mark.parametrize("value,expected", [
    ("-1", ComparisonState.BELOW_RANGE),
    ("0", ComparisonState.BELOW_RANGE),
    ("12.0001", ComparisonState.WITHIN_RANGE),
])
def test_negative_and_tiny_values(value, expected):
    view = make_view(value=value, low=12.0, high=15.0)
    # Negative values are far below; 12.0001 is inside.
    assert compare_result(view).state is expected
