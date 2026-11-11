#!/usr/bin/env python
"""Export representative explanation examples from real pipeline runs.

Cases required by the milestone:

1. fully verified numeric result with a printed reference range
2. verified value with no reference range
3. stratified reference
4. qualitative urine result
5. missing or ambiguous unit
6. OCR-derived result requiring review
7. unknown test

Each file contains the complete explanation record (sections, permissions,
gates, comparison) so the permitted/blocked split is visible.

Usage:
    python tooling/export_explanations.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, DOCS_DIR  # noqa: E402
from mediread.explain import ExplanationEngine  # noqa: E402
from mediread.structured import StructuredExtractionPipeline  # noqa: E402
from mediread.structured.contract import build_explanation_input, load_results  # noqa: E402

OUT = DOCS_DIR / "explanation_examples"


def _explain_file(name: str, engine: ExplanationEngine):
    return engine.explain(load_results(ARTIFACTS_DIR / "results" / f"{name}.results.json"))


def _find(document, test_name: str, page: int | None = None):
    for result in document.results:
        if result.test_name == test_name and (page is None or result.page == page):
            return result
    raise SystemExit(f"example not found: {test_name}")


def _ocr_document(engine: ExplanationEngine):
    extraction = ARTIFACTS_DIR / "extractions_ocr" / "ocr-example.extraction.json"
    if not extraction.exists():
        raise SystemExit(
            "OCR example extraction missing; run tooling/export_examples.py first"
        )
    payload = json.loads(extraction.read_text())
    results = StructuredExtractionPipeline().process(payload)
    return engine.explain(build_explanation_input(results))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    engine = ExplanationEngine()

    main_doc = _explain_file("4f16a4444054fdfe", engine)
    headerless_doc = _explain_file("79bd8cfc0570272b", engine)
    thyroid_doc = _explain_file("c66749371af7e28c", engine)
    ocr_doc = _ocr_document(engine)

    cases = [
        ("01_verified_numeric_with_range", main_doc,
         _find(main_doc, "HEMOGLOBIN", 11),
         "A verified haemoglobin result with a printed interval."),
        ("02_verified_value_no_range", headerless_doc,
         _find(headerless_doc, "Hb A"),
         "A verified value on a page that prints no reference range and no unit."),
        ("03_stratified_reference", main_doc,
         _find(main_doc, "EST. GLOMERULAR FILTRATION RATE (eGFR)"),
         "The report uses a banded eGFR table; no interval comparison is made."),
        ("04_qualitative_urine", main_doc,
         _find(main_doc, "COLOUR", 3),
         "A qualitative urine result compared with the printed qualitative "
         "reference wording."),
        ("05_ambiguous_unit", main_doc,
         _find(main_doc, "MEAN CORPUSCULAR HEMOGLOBIN(MCH)"),
         "The unit is printed as 'pq'; it is not resolved to 'pg' and unit-dependent "
         "comparisons are withheld."),
        ("06_ocr_requires_review", ocr_doc,
         _find(ocr_doc, "ALKALINE PHOSPHATASE"),
         "A genuine OCR-derived result. Every gate is blocked until the user confirms "
         "the text."),
        ("07_unknown_test", thyroid_doc,
         _find(thyroid_doc, "CA-125"),
         "A test with no approved knowledge entry: the report facts and the "
         "deterministic comparison are shown, the education is not."),
    ]

    manifest = []
    for name, _, result, note in cases:
        payload = {
            "example": name,
            "note": note,
            "schema_version": "mediread.explanation/1",
            "knowledge_version": engine.catalogue.version,
            "result": result.to_dict(),
        }
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        permitted = sorted(k for k, v in result.permitted.items() if v)
        blocked = sorted(k for k, v in result.permitted.items() if not v)
        manifest.append(
            {
                "example": name,
                "file": path.name,
                "test": result.test_name,
                "status": result.status.value,
                "knowledge_status": result.knowledge_status,
                "permitted_sections": permitted,
                "blocked_sections": blocked,
                "note": note,
            }
        )
        print(f"{path.name}: {result.test_name} [{result.status.value}] "
              f"permitted={len(permitted)} blocked={len(blocked)}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
