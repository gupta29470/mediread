"""Builders for explanation tests (real contract types, no mocks)."""

from __future__ import annotations

from mediread.structured.contract import (
    EvidenceView,
    FieldView,
    ReferenceBounds,
    ResultGates,
    ResultView,
    UsageGate,
)


def gate(ok: bool, reason: str = "blocked") -> UsageGate:
    return UsageGate(ok, () if ok else ("x",), None if ok else reason)


def field(text, status="verified", *, normalized=None, parsed=None, origin="embedded"):
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
    test_name="HEMOGLOBIN",
    test_id="hemoglobin",
    section="CBC / Hemogram",
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
    value_status="verified",
    unit_status="verified",
    reference_status="verified",
    origin="embedded",
    gates=None,
) -> ResultView:
    bounds = ReferenceBounds(
        low=low,
        high=high,
        low_inclusive=low_inclusive,
        high_inclusive=high_inclusive,
        operator=operator,
        stratified=stratified,
    )
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
        section=section,
        test_name=test_name,
        test_id=test_id,
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
            "test": field(test_name, origin=origin),
            "value": field(value, value_status, parsed=parsed_value, origin=origin),
            "unit": field(unit, unit_status, origin=origin),
            "reference": field(reference, reference_status, origin=origin,
                               parsed=reference_parsed),
        },
        warnings=(),
        row_evidence=None,
        gates=gates or ResultGates(gate(True), gate(True), gate(True), gate(True)),
    )
