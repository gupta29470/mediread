"""End-to-end ingestion pipeline across the four input paths."""

from __future__ import annotations

import pytest

from mediread.ingest.pipeline import IngestionPipeline, merge_region_lines
from mediread.models import BBox, ExtractionMethod, PageClass, SourceKind, TextLine


def _pipeline(engine) -> IngestionPipeline:
    return IngestionPipeline(ocr_engine=engine)


def test_digital_pdf_uses_embedded_text(digital_pdf, fake_engine):
    outcome = _pipeline(fake_engine).process_pdf(digital_pdf)
    doc = outcome.document
    assert doc.page_count == 1
    page = doc.pages[0]
    assert page.method is ExtractionMethod.EMBEDDED_TEXT
    assert page.ocr is None
    assert "HAEMOGLOBIN" in page.text
    assert "13.5" in page.text
    assert fake_engine.calls == 0


def test_digital_pdf_keeps_boxes_and_provenance(digital_pdf):
    outcome = IngestionPipeline().process_pdf(digital_pdf, ocr=False)
    page = outcome.document.pages[0]
    assert page.report_id == outcome.inspection["report_id"]
    assert page.lines
    first = page.lines[0]
    assert first.bbox.x1 > first.bbox.x0
    assert first.words
    assert page.width_pt > 0 and page.height_pt > 0


def test_scanned_pdf_requires_ocr(scanned_pdf, fake_engine):
    outcome = _pipeline(fake_engine).process_pdf(scanned_pdf)
    page = outcome.document.pages[0]
    assert page.page_class is PageClass.SCANNED_IMAGE
    assert page.method is ExtractionMethod.OCR
    assert fake_engine.calls == 1
    assert page.ocr is not None
    assert page.mean_confidence is not None
    assert page.text


def test_scanned_pdf_without_ocr_yields_empty_text(scanned_pdf, fake_engine):
    outcome = _pipeline(fake_engine).process_pdf(scanned_pdf, ocr=False)
    page = outcome.document.pages[0]
    assert page.method is ExtractionMethod.EMPTY
    assert page.text == ""
    assert any("OCR disabled" in w for w in page.warnings)


def test_hybrid_page_merges_and_dedupes(hybrid_pdf, fake_engine):
    # The overlay text is at y=30-55; make the fake engine return a duplicate of
    # it plus one genuinely new line over the raster body.
    # OCR boxes are in image pixels; the page is 595 pt wide. Scale the
    # duplicate so it covers the embedded "Report summary" overlay.
    def provider(image):
        scale = 595 / image.width
        return [
            TextLine(
                text="Report summary",
                bbox=BBox(50 / scale, 25 / scale, 160 / scale, 44 / scale),
                confidence=0.9,
            ),
            TextLine(
                text="RASTER ONLY CONTENT",
                bbox=BBox(50 / scale, 400 / scale, 300 / scale, 420 / scale),
                confidence=0.9,
            ),
        ]

    fake_engine.lines_provider = provider
    outcome = _pipeline(fake_engine).process_pdf(hybrid_pdf)
    page = outcome.document.pages[0]
    assert page.method is ExtractionMethod.HYBRID
    origins = {line.origin for line in page.lines}
    assert origins == {"embedded", "ocr"}
    assert any("duplicates" in w for w in page.warnings)
    assert "RASTER ONLY CONTENT" in page.text


def test_hybrid_without_ocr_keeps_embedded_text(hybrid_pdf, fake_engine):
    outcome = _pipeline(fake_engine).process_pdf(hybrid_pdf, ocr=False)
    page = outcome.document.pages[0]
    assert page.method is ExtractionMethod.EMBEDDED_TEXT
    assert "Report summary" in page.text
    assert fake_engine.calls == 0


def test_image_input_uses_ocr(lab_image, fake_engine):
    outcome = _pipeline(fake_engine).process_image(lab_image)
    doc = outcome.document
    assert doc.page_count == 1
    page = doc.pages[0]
    assert page.source_kind is SourceKind.IMAGE_FILE
    assert page.method is ExtractionMethod.OCR
    assert page.page_class is PageClass.IMAGE_ONLY
    assert fake_engine.calls == 1


def test_image_rejects_unknown_suffix(tmp_path, fake_engine):
    from mediread.errors import MediReadError

    bad = tmp_path / "file.xyz"
    bad.write_bytes(b"nope")
    with pytest.raises(MediReadError):
        _pipeline(fake_engine).process_image(bad)


def test_page_failure_is_isolated(digital_pdf_path, fake_engine, monkeypatch):
    """A failing page must not lose the rest of the document."""
    pipeline = _pipeline(fake_engine)
    from mediread.errors import PageProcessingError

    original = pipeline._process_pdf_page

    def flaky(doc, path, report_id, number, page_stats, ocr):
        if number == 1:
            raise PageProcessingError(number, "simulated corruption")
        return original(doc, path, report_id, number, page_stats, ocr)

    monkeypatch.setattr(pipeline, "_process_pdf_page", flaky)
    outcome = pipeline.process_pdf(digital_pdf_path)
    assert outcome.document.page_count == 2
    assert "SEM" in outcome.document.pages[0].warnings[0] or outcome.document.pages[0].warnings
    assert outcome.document.pages[0].method is ExtractionMethod.EMPTY
    assert "SODIUM" in outcome.document.pages[1].text


def test_merge_region_lines_drops_only_covered():
    embedded = [TextLine(text="Name: X", bbox=BBox(10, 10, 200, 25))]
    duplicate = TextLine(text="Name: X", bbox=BBox(12, 11, 198, 24), origin="ocr")
    fresh = TextLine(text="SODIUM 136.17", bbox=BBox(10, 300, 200, 315), origin="ocr")
    merged, dropped = merge_region_lines(embedded, [duplicate, fresh])
    assert dropped == 1
    assert len(merged) == 2
    assert any(line.text == "SODIUM 136.17" for line in merged)


def test_engine_summary_counts(digital_pdf_path, fake_engine):
    outcome = _pipeline(fake_engine).process_pdf(digital_pdf_path)
    summary = outcome.document.engine_summary
    assert summary["pages"] == 2
    assert summary["embedded_text_pages"] == 2
    assert summary["ocr_pages"] == 0


def test_serialization_roundtrip(digital_pdf, tmp_path):
    import json

    from mediread.ingest.serialization import write_extraction

    outcome = IngestionPipeline().process_pdf(digital_pdf, ocr=False)
    extraction_path, run_path = write_extraction(outcome.document, tmp_path, include_lines=True)
    payload = json.loads(extraction_path.read_text())
    assert payload["schema_version"] == "mediread.extraction/1"
    assert payload["pages"][0]["lines"]
    assert payload["pages"][0]["lines"][0]["bbox"]
    run = json.loads(run_path.read_text())
    assert "dependencies" in run
