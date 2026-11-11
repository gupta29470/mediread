#!/usr/bin/env python
"""Build Flutter assets from the evaluated pipeline.

- assets/eval/cases.json            the fixed 21-case dataset
- assets/eval/canned_e4b.json       recorded E4B outputs from Milestone 3.1
- assets/demo/explanations.json     real mediread.explanation/1 documents
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.explain import ExplanationEngine  # noqa: E402
from mediread.structured import StructuredExtractionPipeline  # noqa: E402
from mediread.structured.contract import build_explanation_input, load_results  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "assets"


def main() -> int:
    cases_path = ROOT / "data" / "llm_eval" / "cases.json"
    cases = json.loads(cases_path.read_text())

    engine = ExplanationEngine()
    by_id = {}

    def record(data, document):
        views = {view.result_id: view for view in data}
        for result in document.results:
            entry = result.to_dict()
            view = views.get(result.result_id)
            if view is not None:
                entry["facts"] = {
                    "value_text": view.value_text,
                    "unit_text": view.unit_text,
                    "reference_text": view.reference_text,
                    "value_kind": view.value_kind,
                    "comparison_state": result.comparison.state.value if result.comparison else None,
                }
            by_id[result.result_id] = entry

    for path in sorted((ROOT / "artifacts" / "results").glob("*.results.json")):
        data = load_results(path)
        record(data, engine.explain(data, generated_at="2026-11-07T00:00:00+00:00"))

    # OCR case: the explanation comes from the OCR extraction path.
    ocr_path = ROOT / "artifacts" / "extractions_ocr" / "ocr-example.extraction.json"
    if ocr_path.exists():
        payload = json.loads(ocr_path.read_text())
        ocr_input = build_explanation_input(StructuredExtractionPipeline().process(payload))
        record(ocr_input, engine.explain(ocr_input))

    canned = {}
    for path in sorted((ROOT / "eval" / "llm" / "run1" / "gemma4-e4b").glob("*.json")):
        record = json.loads(path.read_text())
        raw = record.get("response_raw") or ""
        canned[record["case_id"]] = raw

    # Synthetic contradictory case: a hand-written deterministic document with the
    # same schema, because no corpus row produces two conflicting values.
    synthetic = {
        "result_id": "synthetic-conflict",
        "report_id": "synthetic",
        "page": 1,
        "section": "CBC / Hemogram",
        "test_name": "HEMOGLOBIN",
        "test_id": None,
        "canonical_name": None,
        "knowledge_status": "unsupported",
        "status": "withheld",
        "gates": {"identify_test": False, "interpret_value": False,
                  "unit_comparison": False, "range_comparison": False},
        "permitted": {"what_this_test_measures": False, "your_reported_result": True,
                      "comparison_with_reference": False,
                      "what_this_may_generally_indicate": False,
                      "important_limitations": True, "sources": False},
        "blocked_reasons": ["conflicting rows"],
        "comparison": None,
        "allowed_numbers": [],
        "warnings": ["conflicting values"],
        "facts": {"value_text": None, "unit_text": None, "reference_text": None,
                  "value_kind": "numeric", "comparison_state": None},
        "sections": [
            {"key": "your_reported_result", "kind": "fact", "permitted": True,
             "text": ("The report lists two different haemoglobin values for the same test "
                      "on the same page: 9.0 g/dL and 13.5 g/dL."),
             "reason": None, "sources": [], "partial": False},
            {"key": "important_limitations", "kind": "limitation", "permitted": True,
             "text": ("The two rows for this test carry different values, so MediRead cannot "
                      "decide which one is correct. It will not average them or choose one."),
             "reason": None, "sources": [], "partial": False},
        ],
    }

    explanations = {}
    for case in cases["cases"]:
        result_id = case["facts"].get("result_id")
        if case["case_id"] == "F09_contradictory_information":
            explanations[case["case_id"]] = synthetic
        elif result_id in by_id:
            explanations[case["case_id"]] = by_id[result_id]
        else:
            explanations[case["case_id"]] = None

    # The Flutter app gates the model on an exact review status and shows
    # coverage separately. Engine documents carry coverage (`knowledge_status`,
    # complete/partial/unsupported); the shipped catalogue is the approved one,
    # so a complete entry maps to approved and anything else stays blocked.
    for document in explanations.values():
        if not isinstance(document, dict):
            continue
        coverage = document.get("knowledge_status", "unsupported")
        document.setdefault("knowledge_coverage", coverage)
        document.setdefault(
            "knowledge_review_status", "approved" if coverage == "complete" else "unsupported"
        )

    (OUT / "eval").mkdir(parents=True, exist_ok=True)
    (OUT / "demo").mkdir(parents=True, exist_ok=True)
    (OUT / "eval" / "cases.json").write_text(json.dumps(cases, indent=2))
    (OUT / "eval" / "canned_e4b.json").write_text(json.dumps(canned, indent=2))
    (OUT / "demo" / "explanations.json").write_text(json.dumps(explanations, indent=2))

    missing = [k for k, v in explanations.items() if v is None]
    print(f"cases={len(cases['cases'])} canned={len(canned)} explanations={len(explanations)-len(missing)}")
    print("without a document:", missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
