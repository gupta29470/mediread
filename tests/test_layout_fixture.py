"""Tests for the layout-fixture exporter used by the Dart geometry tests.

The exporter copies character rectangles out of a PDF so the Flutter table
parser can be exercised on the host (pdfium cannot load inside ``flutter test``).
Only synthesised documents are used here, never a patient report.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from tooling.export_layout_fixture import export


def _table_pdf(path: Path) -> Path:
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((40, 60), "TEST NAME", fontsize=9)
    page.insert_text((220, 60), "TECHNOLOGY", fontsize=9)
    page.insert_text((330, 60), "VALUE", fontsize=9)
    page.insert_text((400, 60), "UNITS", fontsize=9)
    page.insert_text((470, 60), "Bio. Ref. Interval.", fontsize=9)
    page.insert_text((40, 80), "CA-125", fontsize=9)
    page.insert_text((220, 80), "C.L.I.A", fontsize=9)
    page.insert_text((330, 80), "29.7", fontsize=9)
    page.insert_text((400, 80), "U/mL", fontsize=9)
    page.insert_text((470, 80), "< 30.2", fontsize=9)
    document.save(path)
    document.close()
    return path


def _page_text(glyphs: list[list]) -> str:
    return "".join(glyph[0] for glyph in glyphs)


def test_export_keeps_reading_order_spaces_and_lines(tmp_path: Path):
    fixture = export(_table_pdf(tmp_path / "table.pdf"))

    assert fixture["pageSizes"] == [[595.0, 842.0]]
    assert len(fixture["pages"]) == 1
    glyphs = fixture["pages"][0]
    assert glyphs, "a page with text must produce glyphs"

    for glyph in glyphs:
        assert len(glyph) == 5
        assert isinstance(glyph[0], str) and len(glyph[0]) == 1
        assert all(isinstance(value, (int, float)) for value in glyph[1:])

    text = _page_text(glyphs)
    assert "CA-125" in text
    assert "Bio. Ref. Interval." in text
    assert text.count("\n") >= 2
    assert any(glyph[0] == " " for glyph in glyphs), "spaces must stay explicit"


def test_export_drops_the_printed_heading_into_reading_order(tmp_path: Path):
    fixture = export(_table_pdf(tmp_path / "table.pdf"))
    glyphs = fixture["pages"][0]
    first_line = "".join(glyph[0] for glyph in glyphs if glyph[0] != "\n").split("CA-125")[0]
    assert first_line.strip().startswith("TEST NAME")
    assert "VALUE" in first_line


def test_export_can_select_pages_and_handles_blank_pages(tmp_path: Path):
    path = tmp_path / "two.pdf"
    document = pymupdf.open()
    first = document.new_page(width=595, height=842)
    first.insert_text((40, 60), "HAEMOGLOBIN", fontsize=9)
    document.new_page(width=595, height=842)  # blank, no text layer
    document.save(path)
    document.close()

    fixture = export(path, [1])
    assert len(fixture["pages"]) == 2
    assert _page_text(fixture["pages"][0]).startswith("HAEMOGLOBIN")
    assert fixture["pages"][1] == []


def test_export_requires_a_path(tmp_path: Path):
    with pytest.raises(Exception):
        export(tmp_path / "missing.pdf")
