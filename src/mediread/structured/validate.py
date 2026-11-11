"""Validation rules applied after field assembly.

Validation never promotes a field to ``verified``; it can only keep a status or
make it more conservative. The checks here are cross-field and cross-result:

* unit dimension versus the test's known dimension (evidence only),
* numeric value versus parsed reference bounds (informational, not a correction),
* duplicate results on a page (same test, same value) and conflicts
  (same test, different value),
* obviously impossible relationships (e.g. a percentage value for a test that
  is never reported as a percentage).
"""

from __future__ import annotations

from decimal import Decimal

from . import vocabulary as vocab
from .schema import FieldStatus, LabResult, ReferenceRange
from .text import in_reference

# Coarse dimensions: enough to catch a unit from the wrong family, not so fine
# that legitimate alternative units (mg/dL vs mg/L) are flagged.
_DIMENSIONS: dict[str, set[str]] = {
    "mass_concentration": {"g/dl", "mg/dl", "mg/l", "ug/dl", "ug/ml", "ng/ml", "ng/dl", "pg/ml"},
    "enzyme_activity": {"u/l", "iu/l", "u/ml", "iu/ml"},
    "substance_concentration": {"mmol/l", "umol/l", "meq/l", "mol/l"},
    "fraction": {"%"},
    "count_per_volume": {"10^3/µl", "10^6/µl", "cells/µl"},
    "count_per_field": {"cells/hpf", "/hpf", "cells/lpf"},
    "volume": {"ml", "l", "µl"},
    "time": {"sec", "seconds"},
    "ratio": {"ratio", "index"},
    "cell_volume": {"fl"},
    "mass": {"pg"},
    "flow": {"ml/min/1.73 m²", "ml/min"},
    "rate": {"mm/hr"},
}

_UNIT_TO_DIMENSION: dict[str, str] = {
    unit: dimension for dimension, units in _DIMENSIONS.items() for unit in units
}


def dimension_of(canonical_unit: str | None) -> str | None:
    if not canonical_unit:
        return None
    return _UNIT_TO_DIMENSION.get(canonical_unit)


def validate_result(result: LabResult) -> LabResult:
    """Apply cross-field rules to one result in place and return it."""
    _check_unit_dimension(result)
    _annotate_reference_relation(result)
    _check_reference_magnitude(result)
    apply_source_policy(result)
    _recompute_status(result)
    return result


# A value this many times outside the parsed interval is treated as a data
# integrity signal, not a clinical statement: dropped decimal points and unit
# conversion mistakes produce exactly this pattern.
MAGNITUDE_FACTOR = 10.0


def _check_reference_magnitude(result: LabResult) -> None:
    parsed = result.reference.parsed or {}
    value_parsed = result.value.parsed or {}
    if result.reference.status is not FieldStatus.VERIFIED:
        return
    if "value" not in value_parsed:
        return
    try:
        value = float(value_parsed["value"])
    except (TypeError, ValueError):
        return
    high = parsed.get("high")
    low = parsed.get("low")
    suspicious = False
    if high is not None and value > max(high, 0.0) * MAGNITUDE_FACTOR and high >= 0:
        suspicious = True
    if low is not None and low > 0 and value < low / MAGNITUDE_FACTOR:
        suspicious = True
    if suspicious:
        result.value.status = FieldStatus.REQUIRES_REVIEW
        result.value.confidence = min(result.value.confidence, 0.5)
        result.value.reasons.append(
            "value is more than 10x outside the reference interval; "
            "possible decimal-point or unit error (value not modified)"
        )
        result.warnings.append("value magnitude inconsistent with reference interval")


def apply_source_policy(result: LabResult) -> None:
    """OCR-derived numbers are never auto-verified.

    A digit substitution is undetectable from the text alone: ``65.63`` and
    ``66.63`` are both well-formed numbers inside the interval. Recognition
    confidence does not make a wrong digit right. Therefore any numeric value or
    unit whose evidence came from OCR is capped at ``requires_review`` and must be
    confirmed by the user, while embedded-text values follow the normal rules.
    """
    if result.value.evidence and result.value.evidence.origin == "ocr":
        if result.value_kind.value in ("numeric", "text") or result.value.status is FieldStatus.VERIFIED:
            if result.value.status is FieldStatus.VERIFIED:
                result.value.status = FieldStatus.REQUIRES_REVIEW
                result.value.reasons.append(
                    "OCR-derived value: not auto-verified, requires user confirmation"
                )
    if result.unit.evidence and result.unit.evidence.origin == "ocr":
        if result.unit.status is FieldStatus.VERIFIED:
            result.unit.status = FieldStatus.REQUIRES_REVIEW
            result.unit.reasons.append(
                "OCR-derived unit: not auto-verified, requires user confirmation"
            )
    if result.reference.evidence and result.reference.evidence.origin == "ocr":
        if result.reference.status is FieldStatus.VERIFIED:
            result.reference.status = FieldStatus.REQUIRES_REVIEW
            result.reference.reasons.append(
                "OCR-derived reference range: not auto-verified, requires user confirmation"
            )
    # The test name identifies *what* is being explained; an OCR-misread name can
    # silently attach an explanation to the wrong analyte, so it follows the same
    # rule as values.
    if result.test.evidence and result.test.evidence.origin == "ocr":
        if result.test.status is FieldStatus.VERIFIED:
            result.test.status = FieldStatus.REQUIRES_REVIEW
            result.test.reasons.append(
                "OCR-derived test name: not auto-verified, requires user confirmation"
            )


def _check_unit_dimension(result: LabResult) -> None:
    if not result.test.normalized or result.unit.status is FieldStatus.MISSING:
        return
    entry = vocab.TEST_ID_TO_ENTRY.get(result.test.normalized)
    if not entry or not entry.expected_units:
        return
    actual_dimension = dimension_of(result.unit.normalized)
    expected_dimensions = {dimension_of(u) for u in entry.expected_units}
    expected_dimensions.discard(None)
    if not actual_dimension or not expected_dimensions:
        return
    if actual_dimension not in expected_dimensions:
        result.unit.status = FieldStatus.REQUIRES_REVIEW
        result.unit.confidence = min(result.unit.confidence, 0.5)
        result.unit.reasons.append(
            f"unit dimension '{actual_dimension}' does not match the expected "
            f"dimension(s) for {entry.display}: {sorted(expected_dimensions)}"
        )
        result.warnings.append("unit/test dimension mismatch")


def _annotate_reference_relation(result: LabResult) -> None:
    """Record whether the value falls inside the parsed range. Informational."""
    reference = result.reference.parsed
    if not reference or result.value.parsed is None:
        return
    try:
        value = Decimal(str(result.value.parsed.get("value")))
    except Exception:
        return
    range_obj = ReferenceRange(
        low=reference.get("low"),
        high=reference.get("high"),
        low_inclusive=reference.get("low_inclusive", True),
        high_inclusive=reference.get("high_inclusive", True),
        operator=reference.get("operator"),
        stratified=reference.get("stratified", False),
    )
    relation = in_reference(value, range_obj)
    if relation is None:
        return
    result.value.parsed["within_reference"] = relation


def aggregate_status(result: LabResult) -> None:
    """Result-level status: trust in the extraction, not completeness.

    A missing reference range is a field-level gap; it does not make the measured
    value less trustworthy, so it does not downgrade the result. An ambiguous or
    malformed range *does*, because it can mislead a reader comparing value and
    range. A numeric value without a unit is never verified.
    """
    from .schema import worst_status

    statuses = [result.test.status, result.value.status]
    if result.qualitative is not None:
        statuses.append(result.qualitative.status)

    explicit_no_unit = result.unit.status is FieldStatus.MISSING and bool(
        (result.unit.raw or "").strip()
    )
    numeric = result.value_kind.value == "numeric"

    if result.unit.status is FieldStatus.MISSING:
        if numeric and not explicit_no_unit:
            statuses.append(FieldStatus.REQUIRES_REVIEW)
    else:
        statuses.append(result.unit.status)

    if result.reference.status in (
        FieldStatus.INVALID,
        FieldStatus.UNCERTAIN,
        FieldStatus.REQUIRES_REVIEW,
    ):
        statuses.append(result.reference.status)

    result.status = worst_status(statuses)
    result.confidence = round(
        sum(f.confidence for f in (result.test, result.value, result.unit, result.reference)) / 4.0,
        3,
    )


def _recompute_status(result: LabResult) -> None:
    aggregate_status(result)


def resolve_duplicates(results: list[LabResult]) -> list[LabResult]:
    """Detect duplicate and conflicting results on the same page.

    The same test can legitimately appear twice (e.g. a repeat), so a conflict
    is not deleted — it is marked ``requires_review`` and both are kept. An exact
    duplicate (same test, same value, same unit, same page) is dropped as an
    extraction artefact and recorded as a warning on the survivor.
    """
    seen: dict[tuple, LabResult] = {}
    output: list[LabResult] = []
    for result in results:
        key = (
            result.page,
            (result.test.raw or "").lower().strip(),
        )
        if key not in seen:
            seen[key] = result
            output.append(result)
            continue

        previous = seen[key]
        same_value = (previous.value.normalized or previous.value.raw) == (
            result.value.normalized or result.value.raw
        )
        same_unit = (previous.unit.normalized or previous.unit.raw) == (
            result.unit.normalized or result.unit.raw
        )
        if same_value and same_unit:
            previous.warnings.append("duplicate row removed (identical test, value and unit)")
            continue

        for item in (previous, result):
            item.status = FieldStatus.REQUIRES_REVIEW
            item.warnings.append(
                "the same test appears more than once on this page with different values"
            )
        output.append(result)
    return output
