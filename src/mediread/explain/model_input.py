"""Versioned model-input contract (``mediread.model-input/1``).

This is the *only* document a language model may see. It is built from the frozen
``mediread.explanation-input/1`` contract plus one knowledge lookup, and it applies
the same field gates:

* a field is included only when its gate allows it **and** the field is verified;
* a blocked field is listed by name in ``withheld_fields`` with no contents;
* the deterministic comparison is included only when both ``interpret_value`` and
  ``range_comparison`` allow it;
* approved knowledge is included only when the lookup is a unique, approved match.

The document is independent of SQLite and byte-stable: ``serialize_model_input``
sorts keys and uses compact separators, so the same facts produce the same bytes.
"""

from __future__ import annotations

import json
from typing import Any

from ..structured.contract import ResultView
from .models import Comparison, ComparisonState
from .package_provider import PackageLookup

SCHEMA_VERSION = "mediread.model-input/1"

TASK = (
    "Explain the supplied, approved information about this laboratory test and this "
    "reported result in plain language for a patient. Use only the facts, knowledge and "
    "comparison provided. Do not add medical facts, numbers, ranges or advice."
)

PROHIBITED_ACTIONS = (
    "diagnose a disease or name a condition as the cause of the result",
    "recommend, start, stop or change any medication or dose",
    "give a prognosis or predict what will happen",
    "claim urgency or say how quickly to seek care",
    "invent, substitute or normalise a reference interval, unit, value or date",
    "infer a disease from a single out-of-range result",
    "claim the result is understood when its fields are unverified or withheld",
    "state any number that is not present in this input",
)

_QUALITATIVE_STATES = (
    ComparisonState.MATCHES_QUALITATIVE_REFERENCE,
    ComparisonState.DIFFERS_FROM_QUALITATIVE_REFERENCE,
)


def _field(view: ResultView, name: str) -> dict[str, Any] | None:
    field = view.fields.get(name)
    if field is None:
        return None
    return {"text": field.text, "status": field.status, "verified": field.is_verified}


def build_model_input(
    view: ResultView,
    lookup: PackageLookup,
    comparison: Comparison | None = None,
    *,
    knowledge_version: str = "",
    evidence_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build the model input for one result. Never includes a blocked value."""
    gates = view.gates
    # Without a permitted knowledge entry there is nothing the model may explain.
    # Ambiguous and unknown results are answered by the deterministic template, so
    # the interpretable facts are withheld from the model entirely: a prompt that
    # contains "4.2 mg/dL, 0.2-1.2" invites a single-test interpretation even when
    # another field says the name is ambiguous.
    deterministic_only = lookup.entry is None
    facts: dict[str, Any] = {}
    withheld: list[str] = []

    def include(name: str, gate_field: str, value: Any, *, condition: bool) -> None:
        if condition and value not in (None, "", ()):
            facts[name] = value
        else:
            withheld.append(name)

    include("test_name", "identify_test", view.test_name,
            condition=(not deterministic_only) and gates.identify_test.allowed
            and _verified(view, "test"))
    include("value_text", "interpret_value", view.value_text,
            condition=(not deterministic_only) and gates.interpret_value.allowed
            and _verified(view, "value"))
    include("unit_text", "unit_comparison", view.unit_text,
            condition=(not deterministic_only) and gates.unit_comparison.allowed
            and _verified(view, "unit"))
    include("reference_text", "range_comparison", view.reference_text,
            condition=(not deterministic_only) and gates.range_comparison.allowed
            and _verified(view, "reference"))

    comparison_payload = None
    comparison_text = getattr(comparison, "description", None)
    if (
        not deterministic_only
        and comparison is not None
        and gates.range_comparison.allowed
        and gates.interpret_value.allowed
        and comparison_text
        and comparison.state not in (ComparisonState.NOT_COMPARABLE_STRATIFIED,)
    ):
        comparison_payload = {
            "state": comparison.state.value,
            "text": comparison_text,
            "reference_text": facts.get("reference_text"),
        }
    else:
        withheld.append("deterministic_comparison")

    review_status = getattr(lookup, "review_status", None)
    template = getattr(lookup, "template", None)
    knowledge = None
    if lookup.entry is not None:
        knowledge = {
            "test_id": lookup.entry.test_id,
            "canonical_name": lookup.entry.canonical_name,
            "what_it_measures": lookup.entry.measures,
            "why_it_is_ordered": lookup.entry.why_ordered,
            "general_interpretation_high": lookup.entry.high_note,
            "general_interpretation_low": lookup.entry.low_note,
            "limitations": list(lookup.entry.limitations),
            "sources": [{"source_id": source_id} for source_id in lookup.entry.sources],
            "review_status": review_status,
            "knowledge_status": getattr(lookup, "match", None),
            "knowledge_version": knowledge_version,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "result_id": view.result_id,
        "page": view.page,
        "mode": "deterministic_only" if deterministic_only else "explain",
        "task": TASK,
        "approved_knowledge": knowledge,
        "verified_facts": facts,
        "withheld_fields": withheld,
        "deterministic_comparison": comparison_payload,
        "limitations": list(lookup.entry.limitations) if lookup.entry else [],
        "permitted_claims": (
            ["what_it_measures", "why_it_is_ordered", "comparison_with_reference"]
            if lookup.entry and comparison_payload
            else ["what_it_measures", "why_it_is_ordered"] if lookup.entry else []
        ),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "deterministic_response": template,
        "claim_references": {
            "knowledge_test_id": lookup.entry.test_id if lookup.entry else None,
            "knowledge_version": knowledge_version if lookup.entry else None,
            "evidence_ids": list(evidence_ids),
            "field_names": list(facts.keys()),
            "comparison_included": comparison_payload is not None,
        },
    }


def _verified(view: ResultView, name: str) -> bool:
    field = view.fields.get(name)
    return field is not None and field.is_verified


def serialize_model_input(model_input: dict[str, Any]) -> str:
    """Canonical JSON: identical facts always produce identical bytes."""
    return json.dumps(model_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
