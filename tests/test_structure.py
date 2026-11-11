"""Geometry: row clustering, column inference, reading order, table probing."""

from __future__ import annotations

import pytest

from mediread.ingest.inspect import open_pdf
from mediread.ingest.structure import (
    assign_segments,
    cluster_rows,
    extract_lines,
    extract_words_exact,
    infer_columns,
    measure_table_structure,
    order_lines,
)
from mediread.models import BBox, TextLine


def test_rows_reconstruct_table(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        rows = cluster_rows(extract_words_exact(doc[0]))
    finally:
        doc.close()
    texts = [row.text for row in rows]
    assert any("HAEMOGLOBIN" in t and "13.5" in t for t in texts), texts
    assert any("PLATELET COUNT" in t and "264" in t for t in texts)


def test_columns_are_inferred(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        rows = cluster_rows(extract_words_exact(doc[0]))
        columns, median_gap = infer_columns(rows)
        counts = assign_segments(rows, columns)
    finally:
        doc.close()
    assert len(columns) >= 3
    assert median_gap > 0
    assert max(counts) >= 4


def test_table_probe_reports_usable(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        probe = measure_table_structure(doc[0])
    finally:
        doc.close()
    assert probe.usable
    assert probe.table_row_count >= 3
    assert probe.modal_segment_count >= 3


def test_table_probe_on_blank_page(blank_pdf):
    doc = open_pdf(blank_pdf)
    try:
        probe = measure_table_structure(doc[0])
    finally:
        doc.close()
    assert not probe.usable
    assert probe.row_count == 0


def test_extract_lines_keeps_verbatim_text(digital_pdf):
    doc = open_pdf(digital_pdf)
    try:
        lines = extract_lines(doc[0])
    finally:
        doc.close()
    text = "\n".join(line.text for line in lines)
    assert "13.5" in text
    assert "3.6" not in text  # nothing invented


def test_verbatim_decimals_survive():
    """The reason layout models are not used for cells: decimals must not move."""
    line = TextLine(
        text="ALANINE TRANSAMINASE 22.53 U/L < 34",
        bbox=BBox(0, 0, 300, 10),
        words=[],
    )
    assert "22.53" in line.text


def test_order_lines_rebuilds_rows():
    lines = [
        TextLine(text="VALUE", bbox=BBox(250, 101, 300, 110)),
        TextLine(text="TEST NAME", bbox=BBox(50, 100, 120, 112)),
        TextLine(text="65.63", bbox=BBox(250, 120, 300, 130)),
        TextLine(text="ALKALINE PHOSPHATASE", bbox=BBox(50, 119, 200, 131)),
    ]
    ordered = order_lines(lines)
    assert [l.text for l in ordered] == ["TEST NAME", "VALUE", "ALKALINE PHOSPHATASE", "65.63"]


def test_order_lines_single_line_is_identity():
    line = TextLine(text="only", bbox=BBox(0, 0, 10, 10))
    assert order_lines([line]) == [line]


def test_cluster_rows_empty():
    assert cluster_rows([]) == []
