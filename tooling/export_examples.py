#!/usr/bin/env python
"""Export the representative contract examples from real pipeline runs.

Each example is produced by running the pipeline, not hand-written, so the
documented JSON cannot drift from the implementation:

1. ``verified_numeric``   — embedded-text result, all fields verified.
2. ``missing_unit``       — numeric result with no printed unit.
3. ``ocr_derived_review`` — genuine OCR run of a rendered page; capped at
                            ``requires_review`` by the source-trust policy.
4. ``qualitative``        — urine strip result ("PALE YELLOW").
5. ``stratified_reference`` — multi-band reference (eGFR).

Usage:
    python tooling/export_examples.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, DOCS_DIR, RAW_DIR  # noqa: E402
from mediread.ingest.pipeline import IngestionPipeline  # noqa: E402
from mediread.ingest.render import render_page, save_raster  # noqa: E402
from mediread.structured import StructuredExtractionPipeline  # noqa: E402
from mediread.structured.contract import build_explanation_input, project_result  # noqa: E402
from mediread.structured.schema import ResultDocument  # noqa: E402

EXAMPLES_DIR = DOCS_DIR / "examples"
OCR_EXTRACTION = ARTIFACTS_DIR / "extractions_ocr"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find(document: ResultDocument, test: str, page: int | None = None):
    for result in document.results:
        if result.test.raw == test and (page is None or result.page == page):
            return result
    raise SystemExit(f"example result not found: {test} (page={page})")


def _ocr_example() -> ResultDocument:
    """Run a real OCR pass over a rendered digital page and extract from it."""
    import pymupdf

    source = RAW_DIR / "0d3182cc9b913364916b208f5d008acb.pdf"
    doc = pymupdf.open(source)
    try:
        raster = render_page(doc[4], dpi=300)   # liver-function page
    finally:
        doc.close()
    # The rendered page contains patient metadata, so it stays under the
    # git-ignored artefacts tree; only the structured example is published.
    png = save_raster(raster, "ocr_example", 5, suffix="_ocr_input",
                      root=ARTIFACTS_DIR / "example_inputs")

    pipeline = IngestionPipeline()
    outcome = pipeline.process_image(png, report_id="ocr-example")
    payload = {
        "schema_version": "mediread.extraction/1",
        "report_id": "ocr-example",
        "source_filename": png.name,
        "source_kind": "image_file",
        "page_count": 1,
        "engine_summary": outcome.document.engine_summary,
        "warnings": outcome.document.warnings,
        "pages": [page.to_dict() for page in outcome.document.pages],
    }
    OCR_EXTRACTION.mkdir(parents=True, exist_ok=True)
    (OCR_EXTRACTION / "ocr-example.extraction.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return StructuredExtractionPipeline().process(payload)


def main() -> int:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    main_doc = StructuredExtractionPipeline().process(
        _load(ARTIFACTS_DIR / "extractions" / "4f16a4444054fdfe.extraction.json")
    )
    headerless_doc = StructuredExtractionPipeline().process(
        _load(ARTIFACTS_DIR / "extractions" / "79bd8cfc0570272b.extraction.json")
    )
    ocr_doc = _ocr_example()

    cases = [
        ("verified_numeric", main_doc, _find(main_doc, "HEMOGLOBIN", 11),
         "Embedded text, every field verified."),
        ("missing_unit", headerless_doc, _find(headerless_doc, "Hb A"),
         "Numeric result on a page with no printed unit; the value is kept, the unit is "
         "missing, and the result cannot be verified."),
        ("ocr_derived_review", ocr_doc, _find(ocr_doc, "ALKALINE PHOSPHATASE"),
         "Genuine Tesseract OCR of a rendered page. Every OCR-derived field is capped at "
         "requires_review by policy, not because this value is known to be wrong."),
        ("qualitative", main_doc, _find(main_doc, "COLOUR", 3),
         "Urine strip qualitative result with the printed reference colour."),
        ("stratified_reference", main_doc, _find(main_doc, "EST. GLOMERULAR FILTRATION RATE (eGFR)", 9),
         "Reference is a stratified band table; bounds are not asserted and the field "
         "requires review."),
    ]

    manifest = []
    for name, document, result, note in cases:
        contract_input = build_explanation_input(document)
        view = project_result(result)
        payload = {
            "example": name,
            "note": note,
            "contract_version": contract_input.contract_version,
            "schema_version": contract_input.schema_version,
            "document": {
                "report_id": contract_input.report_id,
                "source_filename": contract_input.source_filename,
                "generated_at": contract_input.generated_at,
                "sections": list(contract_input.sections),
            },
            "result": view.to_dict(),
        }
        path = EXAMPLES_DIR / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest.append({"example": name, "file": path.name, "note": note,
                         "status": view.status, "test": view.test_name})
        print(f"{path.name}: {view.test_name} status={view.status}")

    (EXAMPLES_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"-> {EXAMPLES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
