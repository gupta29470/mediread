"""End-to-end document ingestion pipeline.

Routing is decided per page from measured structure (:mod:`mediread.ingest.inspect`):

=====================  =========================================================
page class             handling
=====================  =========================================================
``digital_text``       verbatim embedded text + geometry (no OCR)
``scanned_image``      raster (native pixels when available) -> OCR
``image_only``         raster -> OCR
``hybrid``             embedded text **and** OCR of the raster, merged by region
``blank``              recorded as empty
=====================  =========================================================

Hybrid merging is region-level, not textual. OCR lines that the embedded text
layer already covers (>= 50 % of their box overlapping an embedded line) are
dropped as duplicates; OCR lines over raster-only regions are kept and tagged
``origin="ocr"``. Nothing is rewritten: the two sources stay distinguishable in
the output, including in ``PageExtraction.text`` order.

The OCR engine is injected, never imported directly by this module, so replacing
it requires no change downstream.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image

from ..config import DEFAULT_CONFIG, IngestConfig
from ..errors import MediReadError, OcrInferenceError, OcrUnavailableError, PageProcessingError
from ..models import (
    BBox,
    DocumentExtraction,
    ExtractionMethod,
    OcrEngineInfo,
    PageClass,
    PageExtraction,
    SourceKind,
    TextLine,
)
from ..ocr.base import OcrEngine
from ..ocr.registry import create_engine
from .inspect import inspect_document, open_pdf
from .render import PageRaster, full_page_image, rasterise_page, save_raster
from .structure import extract_lines, order_lines

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


@dataclass
class PageOutcome:
    extraction: PageExtraction
    raster: PageRaster | None = None
    lines_embedded: int = 0
    lines_ocr: int = 0
    lines_duplicate_removed: int = 0


@dataclass
class DocumentOutcome:
    document: DocumentExtraction
    inspection: dict | None = None
    pages: list[PageOutcome] = field(default_factory=list)


class IngestionPipeline:
    """Processes PDFs and images into provenance-preserving page extractions."""

    def __init__(
        self,
        cfg: IngestConfig | None = None,
        *,
        ocr_engine: OcrEngine | None = None,
        save_rasters: bool = False,
        raster_root: Path | None = None,
    ) -> None:
        self.cfg = cfg or DEFAULT_CONFIG
        self._engine = ocr_engine
        self.save_rasters = save_rasters
        self.raster_root = raster_root

    # ------------------------------------------------------------------ engine
    @property
    def engine(self) -> OcrEngine:
        if self._engine is None:
            self._engine = create_engine(self.cfg.ocr.engine, language=self.cfg.ocr.language)
        return self._engine

    def engine_info(self) -> OcrEngineInfo | None:
        if self._engine is None:
            return None
        return self._engine.info

    # -------------------------------------------------------------------- pdf
    def process_pdf(
        self,
        path: str | Path,
        *,
        report_id: str | None = None,
        ocr: bool = True,
        pages: list[int] | None = None,
    ) -> DocumentOutcome:
        """Extract a PDF. ``ocr=False`` restricts processing to embedded text."""
        path = Path(path)
        doc = open_pdf(path)
        started = time.perf_counter()
        try:
            stats = inspect_document(doc, path, report_id=report_id, cfg=self.cfg.inspection)
            wanted = pages or list(range(1, doc.page_count + 1))
            outcomes: list[PageOutcome] = []
            warnings: list[str] = []
            for number in wanted:
                page_stats = stats.pages[number - 1]
                try:
                    outcome = self._process_pdf_page(doc, path, stats.report_id, number, page_stats, ocr)
                except (PageProcessingError, OcrInferenceError, OcrUnavailableError) as exc:
                    # A single bad page must not lose the rest of the report.
                    outcome = self._failed_page(stats.report_id, number, page_stats, exc)
                outcomes.append(outcome)
                warnings.extend(outcome.extraction.warnings)

            document = DocumentExtraction(
                report_id=stats.report_id,
                source_filename=path.name,
                source_kind=SourceKind.DIGITAL_PDF,
                page_count=len(outcomes),
                pages=[o.extraction for o in outcomes],
                engine_summary=self._engine_summary(outcomes),
                warnings=warnings,
            )
        finally:
            doc.close()

        document.engine_summary["total_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        return DocumentOutcome(document=document, inspection=stats.to_dict(), pages=outcomes)

    def _process_pdf_page(
        self,
        doc: pymupdf.Document,
        path: Path,
        report_id: str,
        number: int,
        page_stats,
        ocr: bool,
    ) -> PageOutcome:
        page = doc[number - 1]
        timings: dict[str, float] = {}
        warnings: list[str] = []
        page_class: PageClass = page_stats.page_class

        # ------------------------------------------------------- digital text
        if page_class is PageClass.DIGITAL_TEXT:
            t0 = time.perf_counter()
            lines = extract_lines(page)
            timings["extract_embedded"] = (time.perf_counter() - t0) * 1000.0
            method = ExtractionMethod.EMBEDDED_TEXT
            raster = None
            ocr_info = None
            mean_conf = None

            if ocr and self.cfg.allow_ocr_fallback_on_bad_text and page_stats.suspicious_text:
                ocr_lines, raster, ocr_info, ocr_ms = self._ocr_page(doc, number)
                timings["ocr"] = ocr_ms
                if ocr_lines:
                    lines = ocr_lines
                    method = ExtractionMethod.OCR
                    warnings.append("embedded text failed integrity check; OCR used instead")
                    mean_conf = _mean_confidence(ocr_lines)

            extraction = PageExtraction(
                report_id=report_id,
                page_number=number,
                source_kind=SourceKind.DIGITAL_PDF,
                method=method,
                page_class=page_class,
                width_pt=page.rect.width,
                height_pt=page.rect.height,
                text="\n".join(line.text for line in lines),
                lines=lines,
                stats=page_stats,
                ocr=ocr_info,
                rendered_image_path=str(self._persist(raster, report_id, number, "ocr")) if raster else None,
                render_dpi=raster.dpi if raster else None,
                mean_confidence=mean_conf,
                warnings=warnings,
                timings_ms=timings,
            )
            return PageOutcome(extraction=extraction, lines_embedded=len(lines))

        # ------------------------------------------------------------ raster
        if page_class in (PageClass.SCANNED_IMAGE, PageClass.IMAGE_ONLY):
            t0 = time.perf_counter()
            raster = rasterise_page(doc, number, self.cfg.render)
            timings["render"] = (time.perf_counter() - t0) * 1000.0
            if raster.dpi and raster.dpi < 150:
                warnings.append(f"low raster resolution ({raster.dpi} DPI)")
            if not ocr:
                return PageOutcome(
                    extraction=self._empty_page(
                        report_id, number, page_class, page, SourceKind.PDF_PAGE_IMAGE,
                        "OCR disabled but page has no usable text layer", warnings,
                    ),
                    raster=raster,
                )
            t0 = time.perf_counter()
            result = self.engine.recognize(raster.image)
            timings["ocr"] = (time.perf_counter() - t0) * 1000.0
            lines = map_pixels_to_page(result.lines, raster, self._image_target(doc, number, page.rect))
            for line in lines:
                line.origin = "ocr"
            lines = order_lines(lines)
            mean_conf = _mean_confidence(lines)
            if mean_conf is not None and mean_conf < 0.75:
                warnings.append(f"low mean OCR confidence ({mean_conf:.2f})")
            extraction = PageExtraction(
                report_id=report_id,
                page_number=number,
                source_kind=SourceKind.DIGITAL_PDF,
                method=ExtractionMethod.OCR,
                page_class=page_class,
                width_pt=page.rect.width,
                height_pt=page.rect.height,
                text="\n".join(line.text for line in lines),
                lines=lines,
                stats=page_stats,
                ocr=result.engine,
                rendered_image_path=str(self._persist(raster, report_id, number, "ocr")),
                render_dpi=raster.dpi,
                mean_confidence=mean_conf,
                warnings=warnings,
                timings_ms=timings,
            )
            return PageOutcome(extraction=extraction, raster=raster, lines_ocr=len(lines))

        # ------------------------------------------------------------ hybrid
        if page_class is PageClass.HYBRID:
            t0 = time.perf_counter()
            embedded = extract_lines(page)
            timings["extract_embedded"] = (time.perf_counter() - t0) * 1000.0
            if not ocr:
                extraction = PageExtraction(
                    report_id=report_id,
                    page_number=number,
                    source_kind=SourceKind.DIGITAL_PDF,
                    method=ExtractionMethod.EMBEDDED_TEXT,
                    page_class=page_class,
                    width_pt=page.rect.width,
                    height_pt=page.rect.height,
                    text="\n".join(l.text for l in embedded),
                    lines=embedded,
                    stats=page_stats,
                    warnings=warnings + ["hybrid page processed as embedded text only (ocr disabled)"],
                    timings_ms=timings,
                )
                return PageOutcome(extraction=extraction, lines_embedded=len(embedded))

            t0 = time.perf_counter()
            raster = rasterise_page(doc, number, self.cfg.render)
            timings["render"] = (time.perf_counter() - t0) * 1000.0
            t0 = time.perf_counter()
            result = self.engine.recognize(raster.image)
            timings["ocr"] = (time.perf_counter() - t0) * 1000.0

            target = self._image_target(doc, number, page.rect)
            ocr_lines = map_pixels_to_page(result.lines, raster, target)
            for line in ocr_lines:
                line.origin = "ocr"
            ocr_lines = order_lines(ocr_lines)

            t0 = time.perf_counter()
            merged, duplicates = merge_region_lines(embedded, ocr_lines)
            timings["merge"] = (time.perf_counter() - t0) * 1000.0
            if duplicates:
                warnings.append(f"{duplicates} OCR line(s) suppressed as duplicates of the text layer")
            if not ocr_lines:
                warnings.append("OCR returned no text on a hybrid page")

            mean_conf = _mean_confidence([l for l in merged if l.origin == "ocr"])
            extraction = PageExtraction(
                report_id=report_id,
                page_number=number,
                source_kind=SourceKind.DIGITAL_PDF,
                method=ExtractionMethod.HYBRID,
                page_class=page_class,
                width_pt=page.rect.width,
                height_pt=page.rect.height,
                text="\n".join(line.text for line in merged),
                lines=merged,
                stats=page_stats,
                ocr=result.engine,
                rendered_image_path=str(self._persist(raster, report_id, number, "hybrid")),
                render_dpi=raster.dpi,
                mean_confidence=mean_conf,
                warnings=warnings,
                timings_ms=timings,
            )
            return PageOutcome(
                extraction=extraction,
                raster=raster,
                lines_embedded=len(embedded),
                lines_ocr=len(ocr_lines),
                lines_duplicate_removed=duplicates,
            )

        # ------------------------------------------------------------- blank
        return PageOutcome(
            extraction=self._empty_page(
                report_id, number, page_class, page, SourceKind.DIGITAL_PDF,
                "page is blank", warnings,
            )
        )

    # ------------------------------------------------------------------ image
    def process_image(self, path: str | Path, *, report_id: str | None = None) -> DocumentOutcome:
        """OCR a standalone PNG/JPEG/TIFF image (no PDF container)."""
        path = Path(path)
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise MediReadError(f"unsupported image type: {path.suffix}")
        image = Image.open(path)
        image.load()
        rid = report_id or path.stem
        dpi = _image_dpi(image)
        effective = dpi or 72
        width_pt = image.width * 72.0 / effective
        height_pt = image.height * 72.0 / effective

        started = time.perf_counter()
        warnings: list[str] = []
        if dpi is None:
            warnings.append("image has no DPI metadata; coordinates are approximate")
        result = self.engine.recognize(image)
        lines = order_lines(result.lines)
        for line in lines:
            line.origin = "ocr"
        mean_conf = _mean_confidence(lines)
        if mean_conf is not None and mean_conf < 0.75:
            warnings.append(f"low mean OCR confidence ({mean_conf:.2f})")

        stats = _synthetic_page_stats(image, width_pt, height_pt)
        extraction = PageExtraction(
            report_id=rid,
            page_number=1,
            source_kind=SourceKind.IMAGE_FILE,
            method=ExtractionMethod.OCR,
            page_class=PageClass.IMAGE_ONLY,
            width_pt=width_pt,
            height_pt=height_pt,
            text="\n".join(line.text for line in lines),
            lines=lines,
            stats=stats,
            ocr=result.engine,
            mean_confidence=mean_conf,
            warnings=warnings,
            timings_ms={"ocr": (time.perf_counter() - started) * 1000.0},
        )
        document = DocumentExtraction(
            report_id=rid,
            source_filename=path.name,
            source_kind=SourceKind.IMAGE_FILE,
            page_count=1,
            pages=[extraction],
            engine_summary=self._engine_summary([PageOutcome(extraction=extraction)]),
            warnings=warnings,
        )
        return DocumentOutcome(document=document, pages=[PageOutcome(extraction=extraction)])

    # -------------------------------------------------------------- helpers
    def _ocr_page(self, doc: pymupdf.Document, number: int) -> tuple[list[TextLine], PageRaster, OcrEngineInfo, float]:
        raster = rasterise_page(doc, number, self.cfg.render)
        t0 = time.perf_counter()
        result = self.engine.recognize(raster.image)
        elapsed = (time.perf_counter() - t0) * 1000.0
        lines = map_pixels_to_page(result.lines, raster, self._image_target(doc, number, doc[number - 1].rect))
        for line in lines:
            line.origin = "ocr"
        return lines, raster, result.engine, elapsed

    @staticmethod
    def _image_target(doc: pymupdf.Document, number: int, page_rect) -> BBox:
        """Region of the page a raster maps onto (full page for renders)."""
        info = full_page_image(doc[number - 1])
        if info is not None:
            return BBox.from_list(info["bbox"])
        return BBox(page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1)

    def _persist(self, raster: PageRaster | None, report_id: str, number: int, tag: str) -> Path | None:
        if raster is None or not self.save_rasters:
            return None
        return save_raster(raster, report_id, number, suffix=f"_{tag}", root=self.raster_root)

    def _empty_page(
        self,
        report_id: str,
        number: int,
        page_class: PageClass,
        page: pymupdf.Page,
        source_kind: SourceKind,
        reason: str,
        warnings: list[str],
    ) -> PageExtraction:
        stats = _minimal_stats(number, page.rect, page_class)
        return PageExtraction(
            report_id=report_id,
            page_number=number,
            source_kind=source_kind,
            method=ExtractionMethod.EMPTY,
            page_class=page_class,
            width_pt=page.rect.width,
            height_pt=page.rect.height,
            text="",
            lines=[],
            stats=stats,
            warnings=warnings + [reason],
        )

    def _failed_page(self, report_id: str, number: int, page_stats, exc: Exception) -> PageOutcome:
        page_class = page_stats.page_class if page_stats else PageClass.UNKNOWN
        stats = page_stats if page_stats is not None else _minimal_stats(number, None, page_class)
        extraction = PageExtraction(
            report_id=report_id,
            page_number=number,
            source_kind=SourceKind.DIGITAL_PDF,
            method=ExtractionMethod.EMPTY,
            page_class=page_class,
            width_pt=stats.width_pt,
            height_pt=stats.height_pt,
            text="",
            lines=[],
            stats=stats,
            warnings=[f"page failed: {type(exc).__name__}"],
        )
        return PageOutcome(extraction=extraction)

    def _engine_summary(self, outcomes: list[PageOutcome]) -> dict:
        ocr_pages = [o for o in outcomes if o.extraction.method in (ExtractionMethod.OCR, ExtractionMethod.HYBRID)]
        summary: dict = {
            "pages": len(outcomes),
            "embedded_text_pages": sum(1 for o in outcomes if o.extraction.method is ExtractionMethod.EMBEDDED_TEXT),
            "ocr_pages": sum(1 for o in outcomes if o.extraction.method is ExtractionMethod.OCR),
            "hybrid_pages": sum(1 for o in outcomes if o.extraction.method is ExtractionMethod.HYBRID),
            "duplicate_lines_removed": sum(o.lines_duplicate_removed for o in outcomes),
        }
        if ocr_pages:
            info = self.engine_info()
            summary["ocr_engine"] = info.to_dict() if info else None
            latencies = [
                o.extraction.timings_ms.get("ocr", 0.0) for o in ocr_pages
                if o.extraction.timings_ms.get("ocr")
            ]
            if latencies:
                summary["ocr_latency_ms_mean"] = round(sum(latencies) / len(latencies), 1)
        return summary


# ---------------------------------------------------------------- geometry


def map_pixels_to_page(lines: list[TextLine], raster: PageRaster, target: BBox) -> list[TextLine]:
    """Convert OCR pixel boxes into page points for the raster's page region."""
    if raster.width_px <= 0 or raster.height_px <= 0:
        return lines
    sx = target.width / raster.width_px
    sy = target.height / raster.height_px
    for line in lines:
        line.bbox = _map_bbox(line.bbox, target, sx, sy)
        for word in line.words:
            word.bbox = _map_bbox(word.bbox, target, sx, sy)
        for span in line.spans:
            span.bbox = _map_bbox(span.bbox, target, sx, sy)
    return lines


def _map_bbox(bbox: BBox, target: BBox, sx: float, sy: float) -> BBox:
    return BBox(
        target.x0 + bbox.x0 * sx,
        target.y0 + bbox.y0 * sy,
        target.x0 + bbox.x1 * sx,
        target.y0 + bbox.y1 * sy,
    )


def merge_region_lines(
    embedded: list[TextLine], ocr_lines: list[TextLine], overlap_threshold: float = 0.5
) -> tuple[list[TextLine], int]:
    """Merge two line sets, dropping OCR lines already covered by the text layer.

    Coverage is measured on the OCR line's own area, so a large embedded line
    that merely touches a small OCR line does not delete it.
    """
    kept: list[TextLine] = []
    duplicates = 0
    for line in ocr_lines:
        area = line.bbox.area
        if area <= 0:
            kept.append(line)
            continue
        covered = 0.0
        for other in embedded:
            inter = _intersection_area(line.bbox, other.bbox)
            if inter > 0:
                covered += inter
        if covered / area >= overlap_threshold:
            duplicates += 1
            continue
        kept.append(line)
    merged = embedded + kept
    merged.sort(key=lambda l: (round(l.bbox.y0, 1), l.bbox.x0))
    return merged, duplicates


def _intersection_area(a: BBox, b: BBox) -> float:
    width = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    height = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    return width * height


def _mean_confidence(lines: list[TextLine]) -> float | None:
    values = [l.confidence for l in lines if l.confidence is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _image_dpi(image: Image.Image) -> int | None:
    dpi = image.info.get("dpi")
    if isinstance(dpi, tuple) and dpi and dpi[0]:
        return int(round(float(dpi[0])))
    if isinstance(dpi, (int, float)) and dpi:
        return int(round(float(dpi)))
    return None


def _minimal_stats(number: int, rect, page_class: PageClass):
    from ..models import PageStats

    width = rect.width if rect is not None else 0.0
    height = rect.height if rect is not None else 0.0
    return PageStats(
        page_number=number,
        width_pt=width,
        height_pt=height,
        rotation=0,
        char_count=0,
        word_count=0,
        text_block_count=0,
        text_area_ratio=0.0,
        image_count=0,
        image_area_ratio=0.0,
        largest_image_px=None,
        vector_path_count=0,
        horizontal_rule_count=0,
        vertical_rule_count=0,
        font_names=[],
        font_size_min=None,
        font_size_max=None,
        text_alpha_ratio=0.0,
        text_digit_ratio=0.0,
        unique_char_ratio=0.0,
        suspicious_text=False,
        page_class=page_class,
        page_class_reason="not inspected",
        has_embedded_fonts=False,
    )


def _synthetic_page_stats(image: Image.Image, width_pt: float, height_pt: float):
    from ..models import PageStats

    return PageStats(
        page_number=1,
        width_pt=width_pt,
        height_pt=height_pt,
        rotation=0,
        char_count=0,
        word_count=0,
        text_block_count=0,
        text_area_ratio=0.0,
        image_count=1,
        image_area_ratio=1.0,
        largest_image_px=(image.width, image.height),
        vector_path_count=0,
        horizontal_rule_count=0,
        vertical_rule_count=0,
        font_names=[],
        font_size_min=None,
        font_size_max=None,
        text_alpha_ratio=0.0,
        text_digit_ratio=0.0,
        unique_char_ratio=0.0,
        suspicious_text=False,
        page_class=PageClass.IMAGE_ONLY,
        page_class_reason="standalone image input",
        has_embedded_fonts=False,
    )
