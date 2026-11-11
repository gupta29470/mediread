"""Test fixtures.

All documents here are synthesised with PyMuPDF/Pillow in ``tmp_path``. No real
patient report is ever committed to the repository or used in automated tests,
which keeps the suite privacy-safe and fast.
"""

from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image, ImageDraw

from mediread.models import BBox, OcrEngineInfo, OcrPageResult, TextLine, TextWord
from mediread.ocr.base import OcrEngine


def _table_page(**overrides) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 60), "CITY DIAGNOSTIC LABORATORY", fontsize=12)
    page.insert_text((50, 90), "TEST NAME            VALUE      UNITS      REF RANGE", fontsize=9)
    rows = overrides.get(
        "rows",
        [
            ("HAEMOGLOBIN", "13.5", "g/dL", "12.0-15.0"),
            ("TOTAL LEUCOCYTES", "6.02", "10^3/uL", "4.0-10.0"),
            ("PLATELET COUNT", "264", "10^3/uL", "150-410"),
        ],
    )
    y = 115
    for name, value, unit, ref in rows:
        page.insert_text((50, y), f"{name}", fontsize=9)
        page.insert_text((230, y), f"{value}", fontsize=9)
        page.insert_text((310, y), f"{unit}", fontsize=9)
        page.insert_text((410, y), f"{ref}", fontsize=9)
        y += 18
    page.insert_text((50, y + 30), "Method: photometric assay", fontsize=8)
    return doc


@pytest.fixture
def digital_pdf(tmp_path):
    doc = _table_page()
    path = tmp_path / "digital.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def digital_pdf_path(tmp_path):
    doc = _table_page()
    # Add a second page so multi-page behaviour is covered.
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 60), "SECOND PAGE", fontsize=12)
    page.insert_text((50, 90), "TEST NAME            VALUE      UNITS      REF RANGE", fontsize=9)
    for index, (name, value, unit, ref) in enumerate(
        [("SODIUM", "136.17", "mmol/L", "136-145"), ("POTASSIUM", "4.3", "mmol/L", "3.5-5.1"),
         ("CHLORIDE", "103.54", "mmol/L", "98-107"), ("CALCIUM", "9.1", "mg/dL", "8.6-10.3")]
    ):
        y = 115 + index * 18
        page.insert_text((50, y), name, fontsize=9)
        page.insert_text((230, y), value, fontsize=9)
        page.insert_text((310, y), unit, fontsize=9)
        page.insert_text((410, y), ref, fontsize=9)
    page.insert_text((50, 220), "Method: ion selective electrode, measured on an automated analyser", fontsize=8)
    path = tmp_path / "digital_two_pages.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def scanned_pdf(tmp_path):
    """An image-only PDF: the page body is a single raster."""
    source = _table_page()
    pixmap = source[0].get_pixmap(dpi=200)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    source.close()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    path = tmp_path / "scanned.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def hybrid_pdf(tmp_path):
    """A full-page raster with a live text overlay, like the real summary pages."""
    source = _table_page()
    pixmap = source[0].get_pixmap(dpi=150)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    source.close()

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    page.insert_text((50, 40), "Report summary", fontsize=14)
    page.insert_text((50, 60), "Tests asked: complete blood count and lipid profile", fontsize=9)
    page.insert_text((50, 75), "Report status: complete report", fontsize=9)
    page.insert_text((50, 90), "Sample type: EDTA whole blood", fontsize=9)
    path = tmp_path / "hybrid.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def blank_pdf(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    path = tmp_path / "blank.pdf"
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def lab_image(tmp_path):
    """A standalone PNG, as if a page had been exported or photographed."""
    image = Image.new("L", (1240, 1754), 255)
    draw = ImageDraw.Draw(image)
    draw.text((80, 100), "HAEMOGLOBIN      13.5   g/dL   12.0-15.0", fill=0)
    draw.text((80, 140), "PLATELET COUNT   264    10^3/uL 150-410", fill=0)
    path = tmp_path / "page.png"
    image.save(path, format="PNG", dpi=(150, 150))
    return path


class FakeOcrEngine(OcrEngine):
    """Deterministic engine for pipeline tests. No model, no dependency."""

    name = "fake"

    def __init__(self) -> None:
        super().__init__(language="en")
        self.calls = 0
        self.lines_provider = None

    @property
    def info(self) -> OcrEngineInfo:
        return OcrEngineInfo(name=self.name, version="test", model="fake", device="cpu")

    def _recognize(self, image: Image.Image) -> OcrPageResult:
        self.calls += 1
        if self.lines_provider is not None:
            lines = self.lines_provider(image)
        else:
            lines = [
                TextLine(
                    text="HAEMOGLOBIN 13.5 g/dL 12.0-15.0",
                    bbox=BBox(50, 100, 500, 115),
                    words=[TextWord("HAEMOGLOBIN", BBox(50, 100, 150, 115))],
                    confidence=0.95,
                )
            ]
        return OcrPageResult(
            lines=lines,
            engine=self.info,
            image_width=image.width,
            image_height=image.height,
            latency_ms=0.0,
            mean_confidence=0.95,
        )


@pytest.fixture
def fake_engine():
    return FakeOcrEngine()


# --------------------------------------------------------------------------
# Structured-extraction fixtures
# --------------------------------------------------------------------------
# These build ``mediread.extraction/1`` payloads directly, so tests exercise the
# structured layer without PDFs or OCR and remain fast and deterministic.

from mediread.ingest.serialization import document_payload  # noqa: E402


class PageBuilder:
    """Builds an extraction-contract page from rows placed at fixed columns."""

    def __init__(self, page_number: int = 1, width: float = 595.0, height: float = 842.0):
        self.page_number = page_number
        self.width = width
        self.height = height
        self.lines: list[dict] = []
        self._y = 100.0
        self._char_w = 4.5

    def _words(self, text: str, x: float) -> list[dict]:
        words = []
        cursor = x
        for token in text.split(" "):
            if not token:
                continue
            width = len(token) * self._char_w
            words.append(
                {
                    "text": token,
                    "bbox": [round(cursor, 2), round(self._y, 2),
                             round(cursor + width, 2), round(self._y + 9.0, 2)],
                    "confidence": None,
                }
            )
            cursor += width + 2.6
        return words

    def row(self, cells: list[tuple[float, str]], gap_after: float = 12.0) -> "PageBuilder":
        for x, text in cells:
            if not text:
                continue
            words = self._words(text, x)
            if not words:
                continue
            line_text = " ".join(w["text"] for w in words)
            self.lines.append(
                {
                    "text": line_text,
                    "bbox": [words[0]["bbox"][0], words[0]["bbox"][1],
                             words[-1]["bbox"][2], words[-1]["bbox"][3]],
                    "confidence": None,
                    "origin": "embedded",
                    "words": words,
                    "spans": None,
                }
            )
        self._y += gap_after
        return self

    def text(self, value: str, x: float = 26.0, gap_after: float = 12.0) -> "PageBuilder":
        return self.row([(x, value)], gap_after=gap_after)

    def page(self) -> dict:
        return {
            "report_id": "test-report",
            "page_number": self.page_number,
            "source_kind": "digital_pdf",
            "method": "embedded_text",
            "page_class": "digital_text",
            "width_pt": self.width,
            "height_pt": self.height,
            "text": "\n".join(l["text"] for l in self.lines),
            "mean_confidence": None,
            "ocr": None,
            "rendered_image_path": None,
            "render_dpi": None,
            "warnings": [],
            "timings_ms": {},
            "stats": {
                "page_number": self.page_number, "width_pt": self.width,
                "height_pt": self.height, "rotation": 0, "char_count": 500,
                "word_count": 80, "text_block_count": 10, "text_area_ratio": 0.3,
                "image_count": 0, "image_area_ratio": 0.0, "largest_image_px": None,
                "vector_path_count": 0, "horizontal_rule_count": 4,
                "vertical_rule_count": 0, "font_names": ["Arial"],
                "font_size_min": 8.0, "font_size_max": 12.0,
                "text_alpha_ratio": 0.6, "text_digit_ratio": 0.2,
                "unique_char_ratio": 0.2, "suspicious_text": False,
                "page_class": "digital_text", "page_class_reason": "test",
                "has_embedded_fonts": True,
            },
            "lines": self.lines,
        }


class DocBuilder:
    def __init__(self):
        self.pages: list[dict] = []

    def add(self, page: dict) -> "DocBuilder":
        self.pages.append(page)
        return self

    def build(self) -> dict:
        return {
            "schema_version": "mediread.extraction/1",
            "report_id": "test-report",
            "source_filename": "test.pdf",
            "source_kind": "digital_pdf",
            "page_count": len(self.pages),
            "engine_summary": {},
            "warnings": [],
            "pages": self.pages,
        }


COLUMNS_5 = {"test": 26.0, "method": 240.0, "value": 350.0, "unit": 420.0, "range": 480.0}
COLUMNS_4 = {"test": 26.0, "method": 240.0, "value": 380.0, "unit": 450.0}
COLUMNS_4_RANGE = {"test": 26.0, "value": 300.0, "unit": 370.0, "range": 440.0}
COLUMNS_URINE = {"test": 26.0, "value": 250.0, "unit": 380.0, "range": 450.0}


def header_row(columns: dict) -> list[tuple[float, str]]:
    labels = {
        "test": "TEST NAME",
        "method": "TECHNOLOGY",
        "value": "VALUE",
        "unit": "UNITS",
        "range": "Bio. Ref. Interval.",
    }
    return [(x, labels[role]) for role, x in columns.items()]


def build_page(rows: list[dict], columns: dict | None = None, *, urinogram: bool = False) -> dict:
    """Build one page from row dicts with keys test/method/value/unit/range/heading."""
    columns = columns or COLUMNS_5
    builder = PageBuilder(page_number=1)
    if urinogram:
        value_label = "OBSERVATION"
        header = [
            (x, value_label if role == "value" else
             ("TEST NAME" if role == "test" else "UNITS" if role == "unit" else "Bio. Ref. Interval."))
            for role, x in columns.items()
        ]
    else:
        header = header_row(columns)
    builder.row(header)
    for row in rows:
        if row.get("heading"):
            builder.text(row["heading"])
            continue
        cells = []
        for role, x in columns.items():
            text = row.get(role, "")
            if text:
                cells.append((x, text))
        builder.row(cells)
    return builder.page()
