"""Deterministic interpretation of a result against the report's printed range.

No model, no heuristics, no unit conversion. The only inputs are the verified
value and the verified bounds, both taken from the report itself. Every boundary
case is explicit and covered by tests:

* value exactly on an inclusive bound   -> within range
* value exactly on an exclusive bound   -> below / above
* one-sided references (``< 5``, ``> 90``)
* reported bounds rather than measurements (``< 1.003``)
* qualitative results compared with qualitative references
* stratified band tables, which are never treated as an interval

If the ``range_comparison`` gate is not allowed, no comparison is attempted and
``BLOCKED_BY_GATE`` is returned.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ..structured.contract import ResultView
from .models import Comparison, ComparisonState

_WS = re.compile(r"\s+")


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(str(text).strip())
    except (InvalidOperation, ValueError):
        return None


def _normalise_text(text: str | None) -> str:
    if not text:
        return ""
    lowered = text.lower().replace("\u2013", "-").replace("\u2014", "-")
    lowered = lowered.replace("µ", "u")
    return _WS.sub(" ", lowered).strip(" .")


def _bounds_dict(view: ResultView) -> dict:
    bounds = view.reference_bounds
    if bounds is None:
        return {}
    return {
        "low": bounds.low,
        "high": bounds.high,
        "low_inclusive": bounds.low_inclusive,
        "high_inclusive": bounds.high_inclusive,
        "operator": bounds.operator,
        "stratified": bounds.stratified,
    }


def _base(view: ResultView, state: ComparisonState, **kwargs) -> Comparison:
    bounds = _bounds_dict(view)
    return Comparison(
        state=state,
        value_text=view.value_text or "",
        unit_text=view.unit_text,
        reference_text=view.reference_text,
        low=bounds.get("low"),
        high=bounds.get("high"),
        low_inclusive=bounds.get("low_inclusive", True),
        high_inclusive=bounds.get("high_inclusive", True),
        operator=bounds.get("operator"),
        stratified=bounds.get("stratified", False),
        **kwargs,
    )


def compare_result(view: ResultView) -> Comparison:
    """Compare a verified result with the verified printed reference range."""
    if not view.gates.range_comparison.allowed:
        reason = view.gates.range_comparison.reason or "range comparison is not permitted"
        return _base(view, ComparisonState.BLOCKED_BY_GATE, description=reason)

    bounds = _bounds_dict(view)
    if bounds.get("stratified"):
        return _base(view, ComparisonState.NOT_COMPARABLE_STRATIFIED)

    value_field = view.fields["value"]
    parsed_value = value_field.parsed or {}
    if parsed_value.get("bound_operator"):
        # e.g. the report prints "< 1.003" rather than a measured value.
        return _base(view, ComparisonState.NOT_COMPARABLE_VALUE)

    if view.value_kind == "qualitative" or view.value_kind == "text":
        return _compare_qualitative(view, bounds)

    value = _decimal(view.value_number)
    if value is None:
        return _base(view, ComparisonState.NOT_COMPARABLE_VALUE)

    low, high = bounds.get("low"), bounds.get("high")
    if low is None and high is None:
        return _base(view, ComparisonState.NOT_COMPARABLE_MISSING_REFERENCE)

    operator = bounds.get("operator")
    if operator in ("<", "<=") and high is not None:
        satisfies = value < Decimal(str(high)) if operator == "<" else value <= Decimal(str(high))
        return _base(
            view,
            ComparisonState.SATISFIES_ONE_SIDED if satisfies else ComparisonState.VIOLATES_ONE_SIDED,
        )
    if operator in (">", ">=") and low is not None:
        satisfies = value > Decimal(str(low)) if operator == ">" else value >= Decimal(str(low))
        return _base(
            view,
            ComparisonState.SATISFIES_ONE_SIDED if satisfies else ComparisonState.VIOLATES_ONE_SIDED,
        )

    if low is not None:
        low_dec = Decimal(str(low))
        if value < low_dec or (value == low_dec and not bounds.get("low_inclusive", True)):
            return _base(view, ComparisonState.BELOW_RANGE)
    if high is not None:
        high_dec = Decimal(str(high))
        if value > high_dec or (value == high_dec and not bounds.get("high_inclusive", True)):
            return _base(view, ComparisonState.ABOVE_RANGE)
    return _base(view, ComparisonState.WITHIN_RANGE)


def _compare_qualitative(view: ResultView, bounds: dict) -> Comparison:
    reference_text = view.reference_text or ""
    has_numeric_bounds = bounds.get("low") is not None or bounds.get("high") is not None
    if has_numeric_bounds:
        # A descriptive result (e.g. "Normal") against a numeric interval cannot
        # be placed inside or outside that interval.
        return _base(view, ComparisonState.NOT_COMPARABLE_VALUE)
    if not reference_text.strip():
        return _base(view, ComparisonState.NOT_COMPARABLE_MISSING_REFERENCE)
    same = _normalise_text(view.value_text) == _normalise_text(reference_text)
    return _base(
        view,
        ComparisonState.MATCHES_QUALITATIVE_REFERENCE
        if same
        else ComparisonState.DIFFERS_FROM_QUALITATIVE_REFERENCE,
    )
