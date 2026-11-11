"""Ground-truth construction rules and rendering."""

from __future__ import annotations

import pytest

from mediread.evaluation.groundtruth import (
    GroundTruthPage,
    is_identifying,
    load_all_ground_truth,
    load_page_ground_truth,
    looks_like_result_row,
    save_page_ground_truth,
)
from mediread.ingest.inspect import open_pdf
from mediread.ingest.render import (
    full_page_image,
    rasterise_page,
    render_page,
    save_raster,
)


def test_result_rows_accepted():
    assert looks_like_result_row("HAEMOGLOBIN 13.5 g/dL 12.0-15.0")
    assert looks_like_result_row("TEST NAME VALUE UNITS Bio. Ref. Interval.")


def test_prose_rejected():
    long = "An abnormal increase in potassium can profoundly affect the nervous system and cause arrhythmias in patients"
    assert not looks_like_result_row(long)


def test_patient_rows_rejected():
    assert not looks_like_result_row("NAME : GEETA GUPTA(49Y/F)")
    assert not looks_like_result_row("Barcode : 8123456789012")
    assert not looks_like_result_row("Sample Collected on (SCT) : 25/02/2024 09:37")


def test_organisation_rows_rejected():
    assert not looks_like_result_row("Thyrocare Technologies Ltd")
    assert not looks_like_result_row("D37/1 TTC MIDC Industrial Area, Turbhe")


def test_is_identifying():
    assert is_identifying("Ref. By : SELF")
    assert is_identifying("A 104 MOONLIGHT COOPERATIVE HOUSING SOCIETY")
    assert not is_identifying("ALKALINE PHOSPHATASE PHOTOMETRY 65.63 U/L 45-129")


def test_ground_truth_roundtrip(tmp_path):
    page = GroundTruthPage(
        report_id="abc123",
        page_number=2,
        source="embedded_text_layer",
        provenance="test",
        lines=["HAEMOGLOBIN 13.5 g/dL 12.0-15.0"],
        exclude_patterns=[],
        regions=[[10, 10, 100, 20]],
    )
    path = save_page_ground_truth(page, root=tmp_path)
    loaded = load_page_ground_truth(path)
    assert loaded.lines == page.lines
    assert loaded.regions == page.regions
    assert loaded.text == page.text


def test_load_all_ground_truth_ignores_missing_dir(tmp_path):
    assert load_all_ground_truth(tmp_path / "nope") == []


def test_load_missing_raises(tmp_path):
    from mediread.errors import GroundTruthError

    with pytest.raises(GroundTruthError):
        load_page_ground_truth(tmp_path / "missing.json")


def test_render_digital_page(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        raster = render_page(doc[0], dpi=300)
    finally:
        doc.close()
    assert raster.source == "rendered"
    assert raster.dpi == 300
    # A4 width 595 pt at 300 dpi = 2479 px
    assert abs(raster.width_px - 2479) < 5


def test_embedded_raster_preferred_for_scanned_page(scanned_pdf):
    doc = open_pdf(scanned_pdf)
    try:
        assert full_page_image(doc[0]) is not None
        raster = rasterise_page(doc, 1)
    finally:
        doc.close()
    assert raster.source == "embedded"
    assert raster.dpi > 100


def test_save_raster_naming(scanned_pdf, tmp_path):
    doc = open_pdf(scanned_pdf)
    try:
        raster = rasterise_page(doc, 1)
    finally:
        doc.close()
    path = save_raster(raster, "report1", 1, suffix="_ocr", root=tmp_path)
    assert path.exists()
    assert path.name.startswith("p001_embedded")
    assert path.name.endswith("_ocr.png")


def test_digital_page_has_no_full_page_image(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        assert full_page_image(doc[0]) is None
    finally:
        doc.close()
