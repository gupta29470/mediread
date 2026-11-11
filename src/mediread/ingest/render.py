"""Page rasterisation.

Two rendering paths, chosen by what the page actually is:

* **Embedded raster** — a page whose body is one large image (the scanned summary
  pages in this corpus). The original pixels are extracted losslessly instead of
  re-rendering the page. Re-rendering a 150-DPI scan at 300 DPI invents pixels
  and cannot improve recognition; it only doubles the data handed to OCR.
* **Rendered page** — a digital page rasterised at a chosen DPI. Needed when OCR
  is applied to a text page for cross-checking, or when a page has no usable
  text layer and no single full-page image.

Every raster keeps a link to its source: report id, page number, rendering mode
and effective DPI. That link is what lets the evaluation distinguish "OCR on a
PDF page rendered by us" from "OCR on a genuinely scanned document".
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image

from ..config import RENDERED_DIR, RenderConfig
from ..errors import PageProcessingError


@dataclass
class PageRaster:
    """A rasterised page plus the provenance needed to interpret coordinates."""

    image: Image.Image
    width_px: int
    height_px: int
    source: str          # "embedded" | "rendered"
    dpi: int             # effective DPI (computed for embedded rasters)
    mode: str            # PIL mode, e.g. "L" or "RGB"
    xref: int | None = None
    image_bytes: int | None = None


def _px_to_dpi(width_px: int, width_pt: float) -> int:
    if width_pt <= 0:
        return 0
    return int(round(width_px / (width_pt / 72.0)))


def full_page_image(page: pymupdf.Page, min_coverage: float = 0.85) -> dict | None:
    """Return the image info of a single raster covering the page body, if any."""
    images = page.get_image_info(xrefs=True) or []
    if not images:
        return None
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return None
    for image in sorted(images, key=lambda i: _bbox_area(i["bbox"]), reverse=True):
        coverage = _bbox_area(image["bbox"]) / page_area
        if coverage >= min_coverage:
            return image
        break
    return None


def _bbox_area(bbox) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def extract_embedded_raster(doc: pymupdf.Document, page: pymupdf.Page, info: dict) -> PageRaster:
    """Losslessly decode a full-page embedded image."""
    xref = info.get("xref")
    if not xref:
        raise PageProcessingError(page.number + 1, "embedded image has no xref")
    try:
        raw = doc.extract_image(xref)
        image = Image.open(io.BytesIO(raw["image"]))
        image.load()
    except Exception as exc:  # pragma: no cover - corrupt image stream
        raise PageProcessingError(page.number + 1, f"cannot decode embedded image: {exc}") from exc

    if image.mode not in ("L", "RGB"):
        image = image.convert("L" if image.mode in ("1", "LA") else "RGB")
    return PageRaster(
        image=image,
        width_px=image.width,
        height_px=image.height,
        source="embedded",
        dpi=_px_to_dpi(image.width, page.rect.width),
        mode=image.mode,
        xref=xref,
        image_bytes=len(raw["image"]),
    )


def render_page(page: pymupdf.Page, dpi: int = 300, color: bool = False) -> PageRaster:
    """Rasterise a PDF page at ``dpi``."""
    zoom = dpi / 72.0
    matrix = pymupdf.Matrix(zoom, zoom)
    try:
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=pymupdf.csGRAY if not color else pymupdf.csRGB)
    except Exception as exc:  # pragma: no cover - malformed page content
        raise PageProcessingError(page.number + 1, f"render failed: {exc}") from exc
    image = Image.frombytes("L" if not color else "RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return PageRaster(
        image=image,
        width_px=pixmap.width,
        height_px=pixmap.height,
        source="rendered",
        dpi=dpi,
        mode=image.mode,
    )


def rasterise_page(
    doc: pymupdf.Document,
    page_number: int,
    cfg: RenderConfig | None = None,
    *,
    prefer_embedded: bool = True,
) -> PageRaster:
    """Return the best raster for OCR: native embedded pixels when possible."""
    cfg = cfg or RenderConfig()
    page = doc[page_number - 1]
    if prefer_embedded:
        info = full_page_image(page)
        if info is not None:
            raster = extract_embedded_raster(doc, page, info)
            # If the embedded raster is very low resolution, a supersampled
            # render is still not better; keep native pixels and report the DPI
            # so callers can flag it as low quality.
            return raster
    return render_page(page, dpi=cfg.dpi, color=cfg.color)


def save_raster(
    raster: PageRaster,
    report_id: str,
    page_number: int,
    *,
    suffix: str = "",
    root: Path | None = None,
) -> Path:
    """Persist a raster under ``data/rendered/<report_id>/`` with full provenance."""
    root = root or RENDERED_DIR
    target_dir = root / report_id
    target_dir.mkdir(parents=True, exist_ok=True)
    tag = f"p{page_number:03d}_{raster.source}_{raster.dpi}dpi{suffix}.png"
    path = target_dir / tag
    # Embed the effective DPI: when the PNG is later fed back as a standalone
    # image input, the pipeline can recover real page units instead of assuming
    # 72 DPI and warning that coordinates are approximate.
    dpi = (raster.dpi, raster.dpi) if raster.dpi else None
    raster.image.save(path, format="PNG", optimize=True, dpi=dpi)
    return path


def relative_image_size(width_px: int, height_px: int) -> float:
    """Megapixels, for reporting memory/latency drivers."""
    return (width_px * height_px) / 1_000_000.0
