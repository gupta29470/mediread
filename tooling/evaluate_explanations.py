#!/usr/bin/env python
"""Reproducible evaluation of the explanation engine.

Measures, over every structured result in the corpus:

* **completeness**  — how many results get a full, partial or withheld explanation;
* **knowledge coverage** — supported / partial / unsupported test entries;
* **permission compliance** — no section is permitted whose gate is blocked;
* **numerical correctness** — an independent re-implementation of the comparison
  (parsed straight from the reference text) is compared with the engine's state;
* **grounding** — every permitted education section cites a resolvable source;
* **safety** — every generated section is scanned for unsupported claims and for
  numbers that are not in the report facts;
* **determinism** — two runs produce byte-identical JSON.

Every rate is reported with its denominator. No clinical claim is made.

Usage:
    python tooling/evaluate_explanations.py
    python tooling/evaluate_explanations.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, EVAL_DIR  # noqa: E402
from mediread.explain import ExplanationEngine  # noqa: E402
from mediread.explain.knowledge import CATALOGUE, SOURCES  # noqa: E402
from mediread.explain.models import ComparisonState, SectionKey  # noqa: E402
from mediread.explain.safety import validate_document  # noqa: E402
from mediread.structured.contract import load_results  # noqa: E402

_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)")
_UPPER = re.compile(r"<\s*(=)?\s*(\d+(?:\.\d+)?)")
_LOWER = re.compile(r">\s*(=)?\s*(\d+(?:\.\d+)?)")

_ENGINE_TO_INDEPENDENT = {
    ComparisonState.WITHIN_RANGE.value: "within",
    ComparisonState.BELOW_RANGE.value: "below",
    ComparisonState.ABOVE_RANGE.value: "above",
    ComparisonState.SATISFIES_ONE_SIDED.value: "satisfies",
    ComparisonState.VIOLATES_ONE_SIDED.value: "violates",
}


def independent_state(view) -> str | None:
    """Recompute the comparison directly from the printed reference text.

    Deliberately does not use the engine's parsed bounds, so a parsing mistake in
    the engine cannot validate itself.
    """
    if not view.gates.range_comparison.allowed:
        return None
    if view.value_kind != "numeric":
        return None
    if (view.fields["value"].parsed or {}).get("bound_operator"):
        return None
    if view.reference_bounds is None or view.reference_bounds.stratified:
        return None
    text = view.reference_text or ""
    if not text:
        return None

    try:
        value = Decimal(str(view.value_number))
    except Exception:
        return None

    match = _RANGE.search(text)
    if match:
        low, high = Decimal(match.group(1)), Decimal(match.group(2))
        if value < low:
            return "below"
        if value > high:
            return "above"
        return "within"

    match = _UPPER.search(text)
    if match:
        high = Decimal(match.group(2))
        inclusive = bool(match.group(1))
        satisfies = value <= high if inclusive else value < high
        return "satisfies" if satisfies else "violates"

    match = _LOWER.search(text)
    if match:
        low = Decimal(match.group(2))
        inclusive = bool(match.group(1))
        satisfies = value >= low if inclusive else value > low
        return "satisfies" if satisfies else "violates"
    return None


GATE_REQUIREMENTS = {
    SectionKey.WHAT_THIS_TEST_MEASURES.value: ("identify_test",),
    SectionKey.YOUR_REPORTED_RESULT.value: (),
    SectionKey.COMPARISON_WITH_REFERENCE.value: ("range_comparison", "interpret_value"),
    SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE.value: ("identify_test", "interpret_value"),
    SectionKey.IMPORTANT_LIMITATIONS.value: (),
    SectionKey.SOURCES.value: ("identify_test",),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default=str(ARTIFACTS_DIR / "results"))
    parser.add_argument("--out", default=str(EVAL_DIR / "explanations_eval.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    paths = sorted(Path(args.results).glob("*.results.json"))
    if not paths:
        raise SystemExit(f"no result artefacts in {args.results}")

    engine = ExplanationEngine()
    documents = [engine.explain(load_results(path), generated_at="2026-01-01T00:00:00+00:00")
                 for path in paths]

    results = [r for document in documents for r in document.results]
    total_results = len(results)
    total_sections = sum(len(r.sections) for r in results)
    permitted_sections = sum(
        1 for r in results for s in r.sections if s.permitted
    )

    # --- permission compliance -------------------------------------------------
    violations = []
    for result in results:
        for section in result.sections:
            if not section.permitted:
                continue
            for gate in GATE_REQUIREMENTS[section.key.value]:
                if not result.gates.get(gate, False):
                    violations.append(
                        {
                            "test": result.test_name,
                            "section": section.key.value,
                            "gate": gate,
                        }
                    )

    # --- numerical correctness -------------------------------------------------
    numeric_checked = 0
    numeric_mismatches = []
    from mediread.structured.contract import load_results as _load

    for path in paths:
        data = _load(path)
        explained = engine.explain(data, generated_at="2026-01-01T00:00:00+00:00")
        by_id = {r.result_id: r for r in explained.results}
        for view in data:
            expected = independent_state(view)
            if expected is None:
                continue
            numeric_checked += 1
            actual = by_id[view.result_id].comparison
            actual_state = _ENGINE_TO_INDEPENDENT.get(actual.state.value) if actual else None
            if actual_state != expected:
                numeric_mismatches.append(
                    {
                        "result_id": view.result_id,
                        "test": view.test_name,
                        "expected": expected,
                        "engine": actual.state.value if actual else None,
                        "value": view.value_text,
                        "reference": view.reference_text,
                    }
                )

    # --- grounding -------------------------------------------------------------
    education_sections = [
        s for r in results for s in r.sections
        if s.key is SectionKey.WHAT_THIS_TEST_MEASURES and s.permitted
    ]
    grounded = [
        s for s in education_sections
        if s.sources and all(source_id in SOURCES for source_id in s.sources)
    ]

    # --- safety ----------------------------------------------------------------
    findings = []
    for document in documents:
        findings.extend(validate_document(document))
    unsafe_claims = [f for f in findings if f.category != "invented_number"]
    invented_numbers = [f for f in findings if f.category == "invented_number"]

    # --- determinism -----------------------------------------------------------
    rerun = [engine.explain(load_results(path), generated_at="2026-01-01T00:00:00+00:00")
             for path in paths]
    deterministic = all(
        json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
        for a, b in zip(documents, rerun)
    )

    # --- coverage --------------------------------------------------------------
    status_counts: dict[str, int] = {}
    knowledge_counts: dict[str, int] = {}
    for result in results:
        status_counts[result.status.value] = status_counts.get(result.status.value, 0) + 1
        knowledge_counts[result.knowledge_status] = (
            knowledge_counts.get(result.knowledge_status, 0) + 1
        )

    unsupported_names: dict[str, int] = {}
    for result in results:
        if result.knowledge_status == "unsupported":
            unsupported_names[result.test_name] = unsupported_names.get(result.test_name, 0) + 1

    blocked_reasons: dict[str, int] = {}
    for result in results:
        for section in result.sections:
            if not section.permitted and section.reason:
                key = section.reason.split(";")[0][:80]
                blocked_reasons[key] = blocked_reasons.get(key, 0) + 1

    summary = {
        "knowledge_version": CATALOGUE.version,
        "engine_mode": "deterministic",
        "documents": len(documents),
        "results": total_results,
        "sections_total": total_sections,
        "sections_permitted": permitted_sections,
        "permission_violations": len(violations),
        "permission_violation_examples": violations[:10],
        "numeric_checks": numeric_checked,
        "numeric_mismatches": len(numeric_mismatches),
        "numeric_mismatch_examples": numeric_mismatches[:10],
        "education_sections_permitted": len(education_sections),
        "education_sections_grounded": len(grounded),
        "grounding_rate": round(len(grounded) / len(education_sections), 4)
        if education_sections else None,
        "safety_findings": len(findings),
        "unsafe_claims": len(unsafe_claims),
        "invented_numbers": len(invented_numbers),
        "deterministic": deterministic,
        "status_counts": status_counts,
        "knowledge_counts": knowledge_counts,
        "full_explanation_rate": round(
            status_counts.get("explained", 0) / total_results, 4
        ) if total_results else None,
        "blocked_section_reasons": dict(
            sorted(blocked_reasons.items(), key=lambda item: -item[1])[:12]
        ),
        "unsupported_tests": dict(
            sorted(unsupported_names.items(), key=lambda item: -item[1])
        ),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"documents={summary['documents']} results={total_results} "
          f"sections={total_sections} permitted={permitted_sections}")
    print(f"permission violations: {len(violations)} / {permitted_sections} permitted sections")
    print(f"numeric checks: {numeric_checked} mismatches: {len(numeric_mismatches)}")
    print(f"grounding: {len(grounded)}/{len(education_sections)} education sections cite sources")
    print(f"safety findings: {len(findings)} (unsafe claims {len(unsafe_claims)}, "
          f"invented numbers {len(invented_numbers)}) over {permitted_sections} sections")
    print(f"deterministic: {deterministic}")
    print(f"status: {status_counts}")
    print(f"knowledge: {knowledge_counts}")
    if args.verbose:
        print("\nunsupported tests:")
        for name, count in summary["unsupported_tests"].items():
            print(f"  {count:>3}  {name}")
        print("\nblocked section reasons:")
        for reason, count in summary["blocked_section_reasons"].items():
            print(f"  {count:>3}  {reason}")
    print(f"-> {out}")
    failed = bool(violations or numeric_mismatches or findings or not deterministic)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
