"""PDF inspection and page-level content classification.

This module answers, for every page, a single question that drives the rest of
the pipeline: *can the embedded text layer be trusted, or must this page be
rasterised and OCR'd?* It never extracts laboratory values and never writes
document text to disk — it records structural statistics only.

The classifier is intentionally multi-signal (text volume, text area, raster
coverage, vector rules, text integrity) because a single heuristic fails on
this corpus: some pages carry a full header text layer over a scanned table.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pymupdf

from ..config import InspectionConfig
from ..errors import DocumentLoadError, UnsupportedInputError
from ..models import BBox, DocumentStats, PageClass, PageStats
from ..privacy import report_key

SUPPORTED_SUFFIXES = {".pdf"}
_WS = re.compile(r"\s+")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def open_pdf(path: str | Path) -> pymupdf.Document:
    """Open a PDF or raise a typed error. Never logs the path's directory."""
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise UnsupportedInputError(f"not a PDF: {path.suffix}")
    if not path.exists():
        raise DocumentLoadError(f"missing file: {path.name}")
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf raises bare RuntimeError variants
        raise DocumentLoadError(f"cannot open {path.name}: {exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise DocumentLoadError(f"{path.name} is encrypted")
    if doc.page_count == 0:
        doc.close()
        raise DocumentLoadError(f"{path.name} has no pages")
    return doc


def _coverage_ratio(
    rects: Iterable[tuple[float, float, float, float]],
    page_rect: pymupdf.Rect,
    resolution: int,
) -> float:
    """Fraction of the page covered by the union of ``rects``.

    Sampling on a coarse grid is O(res^2) regardless of how many rectangles a
    page contains, which matters for scanned pages with thousands of image
    tiles.
    """
    if page_rect.width <= 0 or page_rect.height <= 0:
        return 0.0
    grid = np.zeros((resolution, resolution), dtype=bool)
    sx = resolution / page_rect.width
    sy = resolution / page_rect.height
    for x0, y0, x1, y1 in rects:
        c0 = max(0, min(resolution - 1, int((x0 - page_rect.x0) * sx)))
        c1 = max(0, min(resolution, int(np.ceil((x1 - page_rect.x0) * sx))))
        r0 = max(0, min(resolution - 1, int((y0 - page_rect.y0) * sy)))
        r1 = max(0, min(resolution, int(np.ceil((y1 - page_rect.y0) * sy))))
        if c1 > c0 and r1 > r0:
            grid[r0:r1, c0:c1] = True
    return float(grid.sum()) / float(resolution * resolution)


def _count_rules(drawings: list[dict]) -> tuple[int, int, int]:
    """Count horizontal/vertical rules and total vector paths.

    Table borders are usually drawn as thin filled rectangles rather than line
    primitives, so both encodings are recognised.
    """
    horizontal = vertical = paths = 0
    for path in drawings:
        paths += 1
        for item in path.get("items", ()):
            kind = item[0]
            if kind == "l":
                p1, p2 = item[1], item[2]
                dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                if dy <= 1.5 and dx >= 8:
                    horizontal += 1
                elif dx <= 1.5 and dy >= 8:
                    vertical += 1
            elif kind == "re":
                rect = item[1]
                if rect.width >= 8 and rect.height <= 2:
                    horizontal += 1
                elif rect.height >= 8 and rect.width <= 2:
                    vertical += 1
    return horizontal, vertical, paths


def _text_integrity(text: str) -> tuple[float, float, float, bool, float | None, float | None]:
    compact = _WS.sub("", text)
    total = len(compact)
    if total == 0:
        return 0.0, 0.0, 0.0, False, None, None
    alpha = sum(ch.isalpha() for ch in compact) / total
    digits = sum(ch.isdigit() for ch in compact) / total
    unique = len(set(compact)) / total
    if "\ufffd" in text:
        suspicious = True
    else:
        words = text.split()
        avg_len = (sum(len(w) for w in words) / len(words)) if words else 0.0
        suspicious = (
            alpha < 0.35
            or unique < 0.03
            or (len(words) >= 12 and avg_len < 2.0)
        )
    return alpha, digits, unique, suspicious, None, None


def _largest_image_px(images: list[dict]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    best_area = 0
    for image in images:
        width = int(image.get("width") or 0)
        height = int(image.get("height") or 0)
        if width * height > best_area:
            best_area = width * height
            best = (width, height)
    return best


def classify_page(
    *,
    char_count: int,
    word_count: int,
    text_area_ratio: float,
    image_area_ratio: float,
    image_count: int,
    suspicious_text: bool,
    cfg: InspectionConfig,
) -> tuple[PageClass, str]:
    """Decide how a page must be processed. Returns the class and a short reason.

    Two signals decide: how much of the page is a raster, and how much is real
    text — with their *relative* coverage, not text volume alone.

    Measured on this corpus, every report opens with a page that is a full-page
    designed raster **plus** a live text overlay carrying the summary fields
    (patient, test panel, date, status). The overlay is content, not residue, so
    such a page is HYBRID and needs region-level routing: keep the embedded text
    and OCR the raster regions that the text layer does not cover.

    A page with a full-page raster and no text at all is genuinely
    scanned/image-only and goes through OCR alone.
    """
    enough_text = char_count >= cfg.min_text_chars and word_count >= cfg.min_text_words
    some_text = char_count > 0
    raster_dominant = image_area_ratio >= cfg.image_cover_threshold
    full_page_raster = image_area_ratio >= cfg.full_page_image_threshold

    if not some_text and image_count == 0:
        return PageClass.BLANK, "no text layer and no images"
    if full_page_raster:
        if some_text:
            return (
                PageClass.HYBRID,
                f"full-page raster ({image_area_ratio:.0%}) with live text overlay "
                f"({char_count} chars); needs region-level routing",
            )
        return (
            PageClass.SCANNED_IMAGE,
            f"full-page raster ({image_area_ratio:.0%}) with no text layer",
        )
    if not some_text and raster_dominant:
        return PageClass.SCANNED_IMAGE, f"no text layer, raster covers {image_area_ratio:.0%} of page"
    if not some_text and image_count > 0:
        return PageClass.IMAGE_ONLY, "images present, no extractable text"
    if raster_dominant and text_area_ratio < cfg.hybrid_text_cover_threshold:
        return (
            PageClass.HYBRID,
            f"raster covers {image_area_ratio:.0%} of the page while text covers "
            f"{text_area_ratio:.0%}; mixed content regions",
        )
    if enough_text and raster_dominant:
        return (
            PageClass.DIGITAL_TEXT,
            f"text layer: {char_count} chars, {word_count} words; raster is page "
            f"furniture ({image_area_ratio:.0%})",
        )
    if enough_text and suspicious_text:
        return PageClass.HYBRID, "text layer present but integrity heuristics failed"
    if enough_text:
        reason = f"text layer: {char_count} chars, {word_count} words"
        if image_count:
            reason += f", page furniture images ({image_area_ratio:.0%})"
        return PageClass.DIGITAL_TEXT, reason
    if raster_dominant or image_count:
        return (
            PageClass.SCANNED_IMAGE,
            f"insufficient text ({char_count} chars) with raster covering {image_area_ratio:.0%}",
        )
    return (
        PageClass.HYBRID,
        f"small text layer ({char_count} chars) without dominant raster, needs OCR",
    )


def analyze_page(page: pymupdf.Page, page_number: int, cfg: InspectionConfig) -> PageStats:
    """Compute structural statistics for one page."""
    rect = page.rect
    text = page.get_text("text", sort=True) or ""
    words = page.get_text("words", sort=True) or []

    dict_blocks = page.get_text("dict")
    text_rects: list[tuple[float, float, float, float]] = []
    fonts: set[str] = set()
    sizes: list[float] = []
    for block in dict_blocks.get("blocks", ()):
        if block.get("type") != 0:
            continue
        bbox = block.get("bbox")
        if bbox:
            text_rects.append(tuple(bbox))
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                if span.get("font"):
                    fonts.add(span["font"])
                if span.get("size"):
                    sizes.append(float(span["size"]))

    images = page.get_image_info(xrefs=True) or []
    image_rects = [tuple(img["bbox"]) for img in images if img.get("bbox")]

    drawings = page.get_drawings() or []
    horizontal, vertical, paths = _count_rules(drawings)

    char_count = len(_WS.sub("", text))
    alpha, digits, unique, suspicious, _, _ = _text_integrity(text)
    text_cover = _coverage_ratio(text_rects, rect, cfg.grid_resolution)
    image_cover = _coverage_ratio(image_rects, rect, cfg.grid_resolution)

    page_class, reason = classify_page(
        char_count=char_count,
        word_count=len(words),
        text_area_ratio=text_cover,
        image_area_ratio=image_cover,
        image_count=len(images),
        suspicious_text=suspicious,
        cfg=cfg,
    )

    return PageStats(
        page_number=page_number,
        width_pt=round(rect.width, 2),
        height_pt=round(rect.height, 2),
        rotation=int(page.rotation),
        char_count=char_count,
        word_count=len(words),
        text_block_count=sum(1 for b in dict_blocks.get("blocks", ()) if b.get("type") == 0),
        text_area_ratio=round(text_cover, 4),
        image_count=len(images),
        image_area_ratio=round(image_cover, 4),
        largest_image_px=_largest_image_px(images),
        vector_path_count=paths,
        horizontal_rule_count=horizontal,
        vertical_rule_count=vertical,
        font_names=sorted(fonts)[:8],
        font_size_min=round(min(sizes), 1) if sizes else None,
        font_size_max=round(max(sizes), 1) if sizes else None,
        text_alpha_ratio=round(alpha, 3),
        text_digit_ratio=round(digits, 3),
        unique_char_ratio=round(unique, 3),
        suspicious_text=suspicious,
        page_class=page_class,
        page_class_reason=reason,
        has_embedded_fonts=bool(fonts),
    )


def inspect_document(
    doc: pymupdf.Document,
    path: Path,
    *,
    report_id: str | None = None,
    cfg: InspectionConfig | None = None,
) -> DocumentStats:
    """Inspect an already-open PDF, avoiding a second parse of the file."""
    cfg = cfg or InspectionConfig()
    metadata = doc.metadata or {}
    pages = [analyze_page(doc[i], i + 1, cfg) for i in range(doc.page_count)]
    classes: dict[str, int] = {}
    for page in pages:
        classes[page.page_class.value] = classes.get(page.page_class.value, 0) + 1
    return DocumentStats(
        report_id=report_id or report_key(path.name),
        source_filename=path.name,
        sha256=sha256_file(path),
        file_size_bytes=path.stat().st_size,
        page_count=doc.page_count,
        pdf_version=metadata.get("format"),
        producer=(metadata.get("producer") or None),
        creator=(metadata.get("creator") or None),
        creation_date=(metadata.get("creationDate") or None),
        is_encrypted=bool(doc.is_encrypted),
        page_classes=classes,
        pages=pages,
    )


def inspect_pdf(
    path: str | Path,
    *,
    report_id: str | None = None,
    cfg: InspectionConfig | None = None,
) -> DocumentStats:
    """Full structural inspection of one PDF. Never persists page text."""
    path = Path(path)
    doc = open_pdf(path)
    try:
        return inspect_document(doc, path, report_id=report_id, cfg=cfg)
    finally:
        doc.close()


def document_profile(stats: DocumentStats) -> str:
    """Coarse label for the inventory: digital / scanned / mixed."""
    classes = set(stats.page_classes)
    if classes <= {PageClass.DIGITAL_TEXT.value}:
        return "digital"
    if classes <= {PageClass.SCANNED_IMAGE.value, PageClass.IMAGE_ONLY.value, PageClass.BLANK.value}:
        return "scanned"
    if PageClass.DIGITAL_TEXT.value in classes and (
        PageClass.SCANNED_IMAGE.value in classes or PageClass.IMAGE_ONLY.value in classes
    ):
        return "mixed"
    return "mixed" if classes else "unknown"
