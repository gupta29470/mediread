"""Domain model for document ingestion.

Everything here is immutable-ish, JSON-serialisable and free of engine-specific
types. The OCR layer converts third-party results into these structures, the
extraction layer consumes them, and provenance (report -> page -> bbox) is
carried all the way through.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Iterable


class SourceKind(str, Enum):
    """Where a page came from. Kept explicit so evaluation never conflates them."""

    DIGITAL_PDF = "digital_pdf"          # embedded text layer, rendered by an authoring tool
    PDF_PAGE_IMAGE = "pdf_page_image"    # a PDF page that is a raster (scanned or image-embedded)
    IMAGE_FILE = "image_file"            # standalone PNG/JPEG input
    PDF_RENDERED_IMAGE = "pdf_rendered_image"  # image rendered *by us* from a digital PDF


class ExtractionMethod(str, Enum):
    EMBEDDED_TEXT = "embedded_text"
    OCR = "ocr"
    HYBRID = "hybrid"          # per-region routing: text layer + OCR on image regions
    EMPTY = "empty"


class PageClass(str, Enum):
    DIGITAL_TEXT = "digital_text"
    SCANNED_IMAGE = "scanned_image"
    HYBRID = "hybrid"          # some text layer, dominant raster body
    IMAGE_ONLY = "image_only"
    BLANK = "blank"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BBox:
    """Axis-aligned box in PDF points (origin top-left) or image pixels."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_list(self) -> list[float]:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]

    @classmethod
    def from_list(cls, values: Iterable[float]) -> "BBox":
        x0, y0, x1, y1 = values
        return cls(float(x0), float(y0), float(x1), float(y1))


@dataclass
class TextSpan:
    """A run of characters sharing font/size — the smallest direct-PDF unit."""

    text: str
    bbox: BBox
    font: str | None = None
    size: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "bbox": self.bbox.to_list(), "font": self.font, "size": self.size}


@dataclass
class TextLine:
    """A visual line. ``words`` are required for table/column reconstruction."""

    text: str
    bbox: BBox
    words: list["TextWord"] = field(default_factory=list)
    spans: list[TextSpan] = field(default_factory=list)
    confidence: float | None = None  # only meaningful for OCR
    origin: str = "embedded"  # "embedded" (PDF text layer) or "ocr"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_list(),
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "origin": self.origin,
            "words": [w.to_dict() for w in self.words],
            "spans": [s.to_dict() for s in self.spans] if self.spans else None,
        }


@dataclass
class TextWord:
    text: str
    bbox: BBox
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "bbox": self.bbox.to_list(),
            "confidence": None if self.confidence is None else round(self.confidence, 4),
        }


@dataclass
class PageStats:
    """Structural facts about one page, used for routing and reporting."""

    page_number: int
    width_pt: float
    height_pt: float
    rotation: int
    char_count: int
    word_count: int
    text_block_count: int
    text_area_ratio: float
    image_count: int
    image_area_ratio: float
    largest_image_px: tuple[int, int] | None
    vector_path_count: int
    horizontal_rule_count: int
    vertical_rule_count: int
    font_names: list[str]
    font_size_min: float | None
    font_size_max: float | None
    text_alpha_ratio: float
    text_digit_ratio: float
    unique_char_ratio: float
    suspicious_text: bool
    page_class: PageClass
    page_class_reason: str
    has_embedded_fonts: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["page_class"] = self.page_class.value
        return data


@dataclass
class DocumentStats:
    report_id: str
    source_filename: str
    sha256: str
    file_size_bytes: int
    page_count: int
    pdf_version: str | None
    producer: str | None
    creator: str | None
    creation_date: str | None
    is_encrypted: bool
    page_classes: dict[str, int]
    pages: list[PageStats]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["pages"] = [p.to_dict() for p in self.pages]
        return data


@dataclass
class OcrEngineInfo:
    name: str
    version: str
    model: str | None = None
    device: str = "cpu"
    language: str = "en"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OcrPageResult:
    lines: list[TextLine]
    engine: OcrEngineInfo
    image_width: int
    image_height: int
    latency_ms: float
    mean_confidence: float | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass
class PageExtraction:
    """The single object downstream code sees, regardless of input path."""

    report_id: str
    page_number: int
    source_kind: SourceKind
    method: ExtractionMethod
    page_class: PageClass
    width_pt: float
    height_pt: float
    text: str
    lines: list[TextLine]
    stats: PageStats
    ocr: OcrEngineInfo | None = None
    rendered_image_path: str | None = None
    render_dpi: int | None = None
    mean_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self, include_lines: bool = True) -> dict[str, Any]:
        data = {
            "report_id": self.report_id,
            "page_number": self.page_number,
            "source_kind": self.source_kind.value,
            "method": self.method.value,
            "page_class": self.page_class.value,
            "width_pt": round(self.width_pt, 2),
            "height_pt": round(self.height_pt, 2),
            "text": self.text,
            "mean_confidence": None if self.mean_confidence is None else round(self.mean_confidence, 4),
            "ocr": self.ocr.to_dict() if self.ocr else None,
            "rendered_image_path": self.rendered_image_path,
            "render_dpi": self.render_dpi,
            "warnings": self.warnings,
            "timings_ms": {k: round(v, 1) for k, v in self.timings_ms.items()},
            "stats": self.stats.to_dict(),
        }
        if include_lines:
            data["lines"] = [line.to_dict() for line in self.lines]
        return data


@dataclass
class DocumentExtraction:
    report_id: str
    source_filename: str
    source_kind: SourceKind
    page_count: int
    pages: list[PageExtraction]
    engine_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)
