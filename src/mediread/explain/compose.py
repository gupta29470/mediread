"""Compose explanations section by section, governed by the permission gates.

Each section has its own eligibility rule:

======================  =====================================================
Section                 Permitted when
======================  =====================================================
what_this_test_measures ``identify_test`` and an approved knowledge entry
your_reported_result    always — it reports what the page prints, marked
                        unconfirmed when ``interpret_value`` is blocked
comparison_with_reference ``range_comparison`` and a decisive comparison
what_this_may_generally_indicate ``identify_test`` and ``interpret_value``
important_limitations   always
sources                 at least one cited source
======================  =====================================================

A blocked section keeps a machine-readable reason so the UI can explain why,
instead of silently omitting it.
"""

from __future__ import annotations

from dataclasses import replace

from ..structured.contract import ResultView
from . import safety
from .interpret import compare_result
from .knowledge.catalogue import KnowledgeCatalogue, LookupResult
from .models import (
    Comparison,
    ComparisonState,
    ResultExplanation,
    ResultExplanationStatus,
    Section,
    SectionKey,
    SectionKind,
)

_NUMERIC_STATE_TEXT = {
    ComparisonState.WITHIN_RANGE: "is inside",
    ComparisonState.BELOW_RANGE: "is below",
    ComparisonState.ABOVE_RANGE: "is above",
}


def explain_result(
    view: ResultView,
    catalogue: KnowledgeCatalogue,
    lookup: "LookupResult | None" = None,
) -> ResultExplanation:
    # A caller (the engine) may resolve the lookup once and pass it in, so the
    # explanation and the model input are guaranteed to use the same knowledge.
    if lookup is None:
        lookup = catalogue.lookup(view.test_id, view.test_name, view.section)
    entry = lookup.entry
    knowledge_status = "unsupported" if entry is None else entry.status

    gates = {
        "identify_test": view.gates.identify_test.allowed,
        "interpret_value": view.gates.interpret_value.allowed,
        "unit_comparison": view.gates.unit_comparison.allowed,
        "range_comparison": view.gates.range_comparison.allowed,
    }

    comparison = compare_result(view)
    comparison = replace(comparison, description=_comparison_text(view, comparison))

    sections: list[Section] = [
        _education_section(view, lookup, gates),
        _reported_result_section(view, gates),
        _comparison_section(view, comparison, gates),
        _general_section(view, lookup, comparison, gates),
        _limitations_section(view, lookup, comparison, gates),
        _sources_section(entry, catalogue, gates),
    ]

    permitted = {section.key.value: section.permitted for section in sections}
    blocked = [f"{s.key.value}: {s.reason}" for s in sections if not s.permitted and s.reason]

    education = permitted[SectionKey.WHAT_THIS_TEST_MEASURES.value]
    comparison_ok = permitted[SectionKey.COMPARISON_WITH_REFERENCE.value]
    if not education and not comparison_ok:
        status = ResultExplanationStatus.WITHHELD
    elif education and comparison_ok:
        status = ResultExplanationStatus.EXPLAINED
    else:
        status = ResultExplanationStatus.PARTIALLY_EXPLAINED

    warnings = _collect_warnings(view, entry, gates)

    return ResultExplanation(
        result_id=view.result_id,
        report_id=view.report_id,
        page=view.page,
        section_name=view.section,
        test_name=view.test_name,
        test_id=view.test_id,
        canonical_name=entry.canonical_name if entry else None,
        knowledge_status=knowledge_status,
        status=status,
        permitted=permitted,
        gates=gates,
        blocked_reasons=blocked,
        sections=sections,
        comparison=comparison,
        warnings=warnings,
        allowed_numbers=frozenset(safety.allowed_numbers_from_view(view)),
    )


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


def _education_section(
    view: ResultView, lookup: LookupResult, gates: dict[str, bool]
) -> Section:
    if not gates["identify_test"]:
        return Section(
            SectionKey.WHAT_THIS_TEST_MEASURES,
            SectionKind.EDUCATION,
            False,
            None,
            reason=(
                "the test name has not been confirmed; explaining what the test measures "
                "could describe the wrong test"
            ),
            sources=(),
        )
    if lookup.entry is None:
        # The package provider carries a specific, deterministic reason; the legacy
        # catalogue keeps its generic wording.
        specific = getattr(lookup, "reason", "") if hasattr(lookup, "template") else ""
        reason = specific or (
            "no approved knowledge entry is available for this test, so MediRead "
            "does not describe it"
        )
        return Section(
            SectionKey.WHAT_THIS_TEST_MEASURES,
            SectionKind.EDUCATION,
            False,
            None,
            reason=reason,
            sources=(),
        )
    entry = lookup.entry
    text = (
        f"{entry.canonical_name}. {entry.measures} {entry.why_ordered}"
    )
    if entry.status == "partial":
        text += (
            " MediRead has only a general description for this test because the "
            "approved sources do not cover it in detail."
        )
    return Section(
        SectionKey.WHAT_THIS_TEST_MEASURES,
        SectionKind.EDUCATION,
        True,
        text,
        sources=entry.sources,
        partial=entry.status == "partial",
    )


def _reported_result_section(view: ResultView, gates: dict[str, bool]) -> Section:
    unit = (view.unit_text or "").strip()
    value = (view.value_text or "").strip()
    test = view.test_name
    no_unit_marker = unit in {"-", "--", "---", "—", "n/a", "na", "nil"}

    if view.value_kind == "qualitative" or view.value_kind == "text":
        sentence = f'Your report lists "{value}" for {test}.'
    elif unit and not no_unit_marker:
        sentence = f"Your report lists {value} {unit} for {test}."
    else:
        sentence = f"Your report lists {value} for {test}, with no unit printed."

    confirmed = gates["interpret_value"]
    if not confirmed:
        sentence += (
            " This value has not been confirmed and should be checked against the "
            "original report before relying on it."
        )
    elif (
        not gates["unit_comparison"]
        and view.value_kind == "numeric"
        and unit
        and not no_unit_marker
    ):
        sentence += (
            " The unit for this result could not be confirmed, so unit-dependent "
            "comparisons are not shown."
        )

    evidence_origin = None
    if view.fields["value"].evidence is not None:
        evidence_origin = view.fields["value"].evidence.origin
    if evidence_origin == "ocr":
        sentence += (
            " This text was read from the report image by OCR, not from a text layer, "
            "and needs confirmation."
        )

    return Section(
        SectionKey.YOUR_REPORTED_RESULT,
        SectionKind.FACT,
        True,
        sentence,
        sources=(),
    )


def _comparison_text(view: ResultView, comparison: Comparison) -> str | None:
    state = comparison.state
    reference = (view.reference_text or "").strip()
    unit = (view.unit_text or "").strip()
    unit_suffix = f" {unit}" if unit and unit not in {"-", "--"} else ""

    if state in _NUMERIC_STATE_TEXT and reference:
        return (
            f"The reported value {_NUMERIC_STATE_TEXT[state]} the reference interval "
            f"printed on your report ({reference}{unit_suffix})."
        )
    if state is ComparisonState.SATISFIES_ONE_SIDED:
        return (
            f"The printed reference is \"{reference}\". The reported value satisfies "
            "that bound."
        )
    if state is ComparisonState.VIOLATES_ONE_SIDED:
        return (
            f"The printed reference is \"{reference}\". The reported value does not "
            "satisfy that bound."
        )
    if state is ComparisonState.MATCHES_QUALITATIVE_REFERENCE:
        return (
            f"The reported result matches the reference wording printed on your report "
            f"(\"{reference}\")."
        )
    if state is ComparisonState.DIFFERS_FROM_QUALITATIVE_REFERENCE:
        return (
            f'The reported result differs from the reference wording printed on your '
            f'report ("{reference}").'
        )
    return None


def _comparison_section(
    view: ResultView, comparison: Comparison, gates: dict[str, bool]
) -> Section:
    if not gates["range_comparison"] or not gates["interpret_value"]:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason=view.gates.range_comparison.reason
            or "comparison with the reference range is not permitted",
        )

    state = comparison.state
    if state is ComparisonState.NOT_COMPARABLE_STRATIFIED:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason=(
                "the report uses a banded (stratified) reference table, so there is no "
                "single interval to compare against"
            ),
        )
    if state is ComparisonState.NOT_COMPARABLE_MISSING_REFERENCE:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason="the report does not print a reference range for this test",
        )
    if state is ComparisonState.NOT_COMPARABLE_UNIT:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason="the units needed for a comparison could not be confirmed",
        )
    if state is ComparisonState.NOT_COMPARABLE_VALUE:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason=(
                "the reported value is descriptive or is a bound rather than a measured "
                "number, so it cannot be placed inside a numeric interval"
            ),
        )
    if not comparison.description:
        return Section(
            SectionKey.COMPARISON_WITH_REFERENCE,
            SectionKind.COMPARISON,
            False,
            None,
            reason="no deterministic comparison could be made",
        )
    return Section(
        SectionKey.COMPARISON_WITH_REFERENCE,
        SectionKind.COMPARISON,
        True,
        comparison.description,
    )


def _general_section(
    view: ResultView, lookup: LookupResult, comparison: Comparison, gates: dict[str, bool]
) -> Section:
    if not gates["identify_test"] or not gates["interpret_value"]:
        reason = (
            "the test or its value has not been confirmed"
            if not gates["identify_test"] or not gates["interpret_value"]
            else "not permitted"
        )
        return Section(
            SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE,
            SectionKind.EDUCATION,
            False,
            None,
            reason=reason,
        )
    if lookup.entry is None:
        return Section(
            SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE,
            SectionKind.EDUCATION,
            False,
            None,
            reason="no approved knowledge entry is available for this test",
        )
    entry = lookup.entry
    parts = [entry.general_note]
    if entry.kind == "qualitative" and entry.qualitative_note:
        parts.append(entry.qualitative_note)
    elif comparison.state is ComparisonState.BELOW_RANGE and entry.low_note:
        parts.append(entry.low_note)
    elif comparison.state is ComparisonState.ABOVE_RANGE and entry.high_note:
        parts.append(entry.high_note)
    elif comparison.state is ComparisonState.VIOLATES_ONE_SIDED:
        # A one-sided bound can be violated in either direction; use both notes
        # only when the test provides them, otherwise stay general.
        if entry.high_note:
            parts.append(entry.high_note)
    parts.append(
        "This is general education about the test, not a statement about your health."
    )
    return Section(
        SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE,
        SectionKind.EDUCATION,
        True,
        " ".join(parts),
        sources=entry.sources,
        partial=entry.status == "partial",
    )


def _limitations_section(
    view: ResultView, lookup: LookupResult, comparison: Comparison, gates: dict[str, bool]
) -> Section:
    parts: list[str] = []
    if lookup.entry is not None:
        parts.extend(lookup.entry.limitations)
    else:
        parts.append(
            "MediRead does not have an approved description for this test, so it cannot "
            "explain what the result means."
        )

    if comparison.state is ComparisonState.NOT_COMPARABLE_STRATIFIED:
        parts.append(
            "The reference information on this report is a table of categories rather "
            "than a single interval; MediRead does not convert it into one."
        )
    if comparison.state is ComparisonState.NOT_COMPARABLE_MISSING_REFERENCE:
        parts.append("No reference range is printed for this test on this report.")
    if comparison.state is ComparisonState.NOT_COMPARABLE_VALUE:
        parts.append(
            "The result is descriptive or is reported as a bound, so a numeric "
            "in-range or out-of-range statement is not possible."
        )
    if not gates["unit_comparison"]:
        parts.append("The unit for this result could not be confirmed.")

    value_origin = None
    if view.fields["value"].evidence is not None:
        value_origin = view.fields["value"].evidence.origin
    if value_origin == "ocr":
        parts.append(
            "The value was read by OCR and has not been confirmed; it should be "
            "checked against the original report."
        )
    if not gates["interpret_value"]:
        parts.append(
            "MediRead has not interpreted this value; it is shown as it appears on the "
            "report and marked unconfirmed."
        )
    if not gates["identify_test"]:
        parts.append(
            "The test name has not been confirmed, so MediRead does not explain what "
            "the test measures."
        )

    parts.append(
        "MediRead does not have your symptoms, medical history, medicines or other test "
        "results, and cannot assess how urgent any result is."
    )
    return Section(
        SectionKey.IMPORTANT_LIMITATIONS,
        SectionKind.LIMITATION,
        True,
        " ".join(parts),
    )


def _sources_section(entry, catalogue: KnowledgeCatalogue, gates: dict[str, bool]) -> Section:
    if not gates["identify_test"]:
        return Section(
            SectionKey.SOURCES,
            SectionKind.REFERENCE,
            False,
            None,
            reason="the test name has not been confirmed, so no source is attributed",
        )
    if entry is None:
        return Section(
            SectionKey.SOURCES,
            SectionKind.REFERENCE,
            False,
            None,
            reason="no sources to cite for an unsupported test",
        )
    sources = catalogue.sources_for(entry)
    lines = [
        f"{source['title']} — {source['organization']}. {source['url']} "
        f"(accessed {source['accessed']})."
        for source in sources
    ]
    return Section(
        SectionKey.SOURCES,
        SectionKind.REFERENCE,
        True,
        " ".join(lines) + " " + "Source: MedlinePlus, National Library of Medicine.",
        sources=tuple(source["source_id"] for source in sources),
    )


def _collect_warnings(view: ResultView, entry, gates: dict[str, bool]) -> list[str]:
    warnings: list[str] = []
    if not gates["identify_test"]:
        warnings.append("test name not confirmed")
    if not gates["interpret_value"]:
        warnings.append("value not confirmed")
    if not gates["range_comparison"]:
        warnings.append("comparison with the reference range withheld")
    if entry is None:
        warnings.append("test not in knowledge base")
    elif entry.status == "partial":
        warnings.append("knowledge entry is partial")
    return warnings
