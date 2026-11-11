# MediRead — ingestion architecture

Status: Phase 1 (ingestion), Phase 2 (structured results) and Phase 3
(explanations) implemented. The top-level README covers the project overview,
the mobile app and how to run the suites.

This document describes the document-ingestion layer only. Laboratory-value
extraction, explanation generation, local storage and the mobile client are
subsequent layers; the interfaces they will consume are defined here.

## 1. Design constraints that shaped it

| Constraint | Consequence |
|-----------|-------------|
| A wrong value is worse than a missing value | verbatim text tokens, no layout model, no OCR post-correction |
| Reports differ per page and per producer | per-page classification and routing, not per-document |
| Privacy first | local-only inference, no network calls, redacting logger, artefacts gated by explicit output dir |
| OCR engines differ by content type | provider-agnostic engine interface, injectable, measurable |
| Must support new report categories | extraction consumes a generic page/line/word contract, not lab-specific structure |
| Must stay debuggable on a tiny corpus | every stage is a pure function over an explicit data model |

## 2. Layers

```text
                       ┌───────────────────────────────────────────────┐
  PDF / PNG / JPEG ──► │ 1. Inspect      (ingest/inspect.py)           │
                       │    page stats + page class per page           │
                       └───────────────┬───────────────────────────────┘
                                       │ PageStats (class, coverage, rules, integrity)
                       ┌───────────────▼───────────────────────────────┐
                       │ 2. Route        (ingest/pipeline.py)          │
                       │    digital → embedded text                    │
                       │    raster  → render/extract → OCR             │
                       │    hybrid  → both, merged by region           │
                       └───┬───────────────────────────────┬───────────┘
                           │                               │
        ┌──────────────────▼──────────┐      ┌─────────────▼───────────────┐
        │ 3a. Embedded text           │      │ 3b. Raster + OCR            │
        │  ingest/structure.py        │      │  ingest/render.py           │
        │  exact words, spans, boxes  │      │  ingest/preprocess.py       │
        │  row / column reconstruction│      │  ocr/base.py + engines      │
        └──────────────────┬──────────┘      └─────────────┬───────────────┘
                           └───────────────┬───────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 4. Normalise to page space                    │
                       │    pixel → points, geometric reading order    │
                       │    region merge, duplicate suppression        │
                       └───────────────────┬───────────────────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 5. Serialise   (ingest/serialization.py)      │
                       │    extraction JSON + run metadata JSON        │
                       └───────────────────┬───────────────────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 6. Structured results (structured/)           │
                       │    rows → fields → validation → results/1     │
                       └───────────────────┬───────────────────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 7. Contract (structured/contract.py)          │
                       │    load + validate + project → ExplanationInput│
                       └───────────────────┬───────────────────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 8. Explanation (explain/)                     │
                       │    catalogue → compare → compose → safety     │
                       └───────────────────┬───────────────────────────┘
                       ┌───────────────────▼───────────────────────────┐
                       │ 9. Consume (next phase)                       │
                       │    review UI → storage                        │
                       └───────────────────────────────────────────────┘
```

## 3. Module responsibilities

| Module | Responsibility | Never does |
|--------|----------------|-----------|
| `config.py` | thresholds, DPI, engine choice, env overrides | contain magic numbers elsewhere |
| `models.py` | immutable data model shared by all layers | import an OCR library |
| `privacy.py` | redaction, redacting log filter, opaque report ids | log raw text |
| `ingest/inspect.py` | page stats, classification, document profile | extract text for output |
| `ingest/structure.py` | words → rows → columns → reading order | parse laboratory values |
| `ingest/render.py` | rasterise, prefer native embedded pixels | resample a scan up |
| `ingest/preprocess.py` | optional grayscale/denoise/deskew/binarise variants | alter text content |
| `ingest/pipeline.py` | routing, merging, provenance, per-page error isolation | know which OCR engine is used |
| `ingest/serialization.py` | stable JSON contract + run metadata | print patient text |
| `ocr/base.py` | engine interface, grouping helpers, confidence normalisation | contain engine code |
| `ocr/<engine>.py` | one provider each | be imported by the pipeline directly |
| `ocr/registry.py` | name → engine, availability probe | import heavy deps eagerly |
| `evaluation/metrics.py` | CER/WER + numeric/decimal/unit/range errors | be used at runtime |

## 4. Page routing rules

`classify_page` is a pure function of measured signals. Rules are evaluated in
order; the first match wins.

| # | Condition | Class | Handling |
|---|-----------|-------|----------|
| 1 | no text and no images | `blank` | record empty page |
| 2 | raster ≥ 85 % of page **and** text present | `hybrid` | embedded text + OCR, merged |
| 3 | raster ≥ 85 % and no text | `scanned_image` | OCR only |
| 4 | raster ≥ 30 % and text area < 6 % | `hybrid` | embedded text + OCR, merged |
| 5 | ≥ 120 chars and ≥ 15 words | `digital_text` | embedded text only |
| 6 | text present but integrity heuristics fail | `hybrid` | OCR cross-check |
| 7 | images but no text | `image_only` | OCR only |
| 8 | small text layer, no raster | `hybrid` | OCR |

Standalone image input (`process_image`) always takes the OCR path and records
`source_kind = image_file`.

**Why rule 2 exists.** Measured on the corpus, every multi-page report starts
with a full-page 150 DPI raster that carries the lab's letterhead *and* a live
text overlay with the summary fields. Classifying it as a scan would lose the
overlay; classifying it as digital would lose the letterhead. The overlay is
also not duplicated in the raster, so a whole-page choice cannot be correct.

## 5. Data contract

The unit exchanged between OCR, text extraction and everything downstream is
`TextLine`:

```jsonc
{
  "text": "ALANINE TRANSAMINASE (SGPT)",
  "bbox": [27.0, 318.4, 197.0, 329.3],   // PDF points, origin top-left
  "confidence": null,                    // null for embedded text
  "origin": "embedded",                  // "embedded" | "ocr"
  "words": [{"text": "...", "bbox": [...], "confidence": null}],
  "spans": [{"text": "...", "bbox": [...], "font": "Arial", "size": 8.9}]
}
```

`PageExtraction` adds page identity, provenance, method, engine metadata,
timings, warnings and the structural `PageStats`. `DocumentExtraction` adds
report identity and an engine summary. The full JSON schema version is
`mediread.extraction/1`.

Two properties matter downstream:

1. **Every token has a box on its page.** Any extracted laboratory value can be
   traced back to a rectangle on a page of a specific report.
2. **Origin is never collapsed.** An explanation can state whether a value came
   from the PDF's own text layer or from OCR, and with what confidence.

## 6. Provenance model

`report_id (sha256 prefix) → page_number → bbox`, plus:

- source file name and full SHA-256 in the run metadata;
- source kind (`digital_pdf`, `pdf_page_image`, `image_file`);
- rendering mode (`embedded` native pixels vs `rendered` at N DPI) and effective DPI;
- engine name, version, model identifier and language;
- per-stage timings and warnings.

Rendered images are written only when `--save-rasters` is passed and are named
`p{page:03d}_{source}_{dpi}dpi_{tag}.png` under `data/rendered/<report_id>/`, so
an image can never be confused with its source PDF or with a genuine scan.

## 7. Privacy enforcement

| Risk | Control | Where |
|------|---------|-------|
| report text in logs | `RedactingFilter` on the only handler; `configure_logging` is the sole entry point | `privacy.py` |
| identifiers in diagnostics | every CLI/console diagnostic passes through `redact_text` | `privacy.py`, `cli.py` |
| patient text in artefacts | artefacts only written to an explicit local directory; the logger never receives it | `serialization.py` |
| filenames revealing identity | `report_key()` hashes the name; outputs are keyed by the hash | `privacy.py` |
| network egress | no HTTP client anywhere in the package; all engines are local | all |
| training on reports | no training code in this phase; evaluation reads reports read-only | — |
| telemetry | ONNX Runtime may emit a local telemetry-device warning on macOS; no data is transmitted, and the warning is stderr-only | note in evaluation doc |

`redact_text` is tested in both directions: identifiers must be masked **and**
laboratory values, units and reference ranges must survive unchanged. Masking a
reference range would make extraction bugs undebuggable, so date patterns
require a four-digit year or a month name. 20 automated assertions cover this.

## 8. Error handling

Errors are typed (`errors.py`) and handled at the narrowest useful scope:

- **Document level**: `DocumentLoadError` for missing, corrupt or encrypted
  files; `UnsupportedInputError` for wrong suffixes. The CLI reports and moves on.
- **Page level**: `PageProcessingError` / `OcrInferenceError` are caught per page;
  the page is recorded with `method = "empty"` and a warning, and the remaining
  pages are still processed. Verified by `test_page_failure_is_isolated`.
- **Engine level**: `OcrUnavailableError` distinguishes "not installed" from
  "failed on this image" and names the install command.

Warnings are structured strings on the page, not exceptions: low raster DPI,
low mean OCR confidence, duplicate OCR lines removed, OCR disabled on a raster
page, integrity-check fallback taken.

## 9. Extending the system

**Another OCR engine.** Implement `OcrEngine` (`_recognize` + `info`), convert
boxes to pixel coordinates, normalise confidence to `[0,1]`, register it in
`ocr/registry.py`. No pipeline change. The interface was validated by four
independent implementations (Tesseract, Apple Vision, RapidOCR, PaddleOCR).

**Another laboratory or report category.** Nothing in the ingestion layer is
category-specific: it produces pages, rows, columns and tokens. A new category
adds a row-parsing profile (test-name vocabulary, expected units) downstream;
it does not touch ingestion.

**A different table geometry.** `infer_columns` is parameterised (`gap_factor`,
`min_gap_pt`, `boundary_tolerance_pt`, `min_row_support`) and falls back to
per-row classification when no band is found.

## 10. Determinism and reproducibility

- Direct extraction is deterministic: same PDF → same bytes of output.
- Tesseract is deterministic with a pinned model and CLI flags.
- Apple Vision depends on the macOS build; the OS version is recorded in engine
  metadata and results must be re-baselined after an OS upgrade.
- Dependencies are pinned in `pyproject.toml`; the run metadata records resolved
  versions, configuration and the source file digest.
- Evaluation ground truth and results are versioned under `data/ground_truth/`
  and `eval/`.

## 11. Deliberately out of scope for this phase

- Laboratory-value extraction and validation (next phase).
- Explanation generation and medical reference content.
- Local encrypted storage and history comparison.
- Mobile client and OS-level PDF ingestion.
- Model fine-tuning: the brief defers it until a measured baseline exists, and
  the baseline now exists (see `docs/ocr_evaluation.md`).
