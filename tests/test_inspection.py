"""Page inspection and classification."""

from __future__ import annotations

import pymupdf
import pytest

from mediread.config import InspectionConfig
from mediread.ingest.inspect import (
    analyze_page,
    document_profile,
    inspect_document,
    inspect_pdf,
    open_pdf,
)
from mediread.models import PageClass


def test_digital_page_is_digital(digital_pdf):
    stats = inspect_pdf(digital_pdf)
    assert stats.page_count == 1
    page = stats.pages[0]
    assert page.page_class is PageClass.DIGITAL_TEXT
    assert page.char_count > 50
    assert page.image_area_ratio < 0.1
    assert document_profile(stats) == "digital"


def test_scanned_page_requires_ocr(scanned_pdf):
    stats = inspect_pdf(scanned_pdf)
    page = stats.pages[0]
    assert page.page_class is PageClass.SCANNED_IMAGE
    assert page.image_area_ratio > 0.9
    assert page.char_count == 0
    assert "raster" in page.page_class_reason


def test_hybrid_page_detected(hybrid_pdf):
    stats = inspect_pdf(hybrid_pdf)
    page = stats.pages[0]
    assert page.page_class is PageClass.HYBRID
    assert "region-level" in page.page_class_reason


def test_blank_page(blank_pdf):
    stats = inspect_pdf(blank_pdf)
    assert stats.pages[0].page_class is PageClass.BLANK


def test_document_profile_mixed(hybrid_pdf):
    assert document_profile(inspect_pdf(hybrid_pdf)) == "mixed"


def test_multi_page_stats(digital_pdf_path):
    stats = inspect_pdf(digital_pdf_path)
    assert stats.page_count == 2
    assert [p.page_number for p in stats.pages] == [1, 2]
    assert all(p.page_class is PageClass.DIGITAL_TEXT for p in stats.pages)


def test_open_pdf_rejects_missing_file(tmp_path):
    from mediread.errors import DocumentLoadError

    with pytest.raises(DocumentLoadError):
        open_pdf(tmp_path / "nope.pdf")


def test_open_pdf_rejects_non_pdf(tmp_path):
    from mediread.errors import UnsupportedInputError

    other = tmp_path / "x.txt"
    other.write_text("hello")
    with pytest.raises(UnsupportedInputError):
        open_pdf(other)


def test_encrypted_pdf_rejected(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "locked.pdf"
    doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    from mediread.errors import DocumentLoadError

    with pytest.raises(DocumentLoadError):
        open_pdf(path)


def test_analysis_is_deterministic(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        first = analyze_page(doc[0], 1, InspectionConfig()).to_dict()
        second = analyze_page(doc[0], 1, InspectionConfig()).to_dict()
    finally:
        doc.close()
    assert first == second


def test_inspect_document_matches_inspect_pdf(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        from pathlib import Path

        a = inspect_document(doc, Path(digital_pdf)).to_dict()
    finally:
        doc.close()
    b = inspect_pdf(digital_pdf).to_dict()
    assert a["page_classes"] == b["page_classes"]
    assert a["sha256"] == b["sha256"]
