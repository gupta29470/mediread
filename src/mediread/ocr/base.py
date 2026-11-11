"""OCR provider interface.

Downstream code must never depend on a specific engine. Everything an engine
produces is converted into :class:`~mediread.models.OcrPageResult` with:

* one :class:`TextLine` per recognised text line,
* boxes in **image pixel** coordinates (origin top-left),
* confidence in ``[0, 1]`` (engines that report 0-100 are normalised here),
* the engine's identity and version for reproducibility.

The pipeline converts pixel boxes to PDF points, so a consumer of the final
``PageExtraction`` always works in page coordinates regardless of engine.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Sequence

from PIL import Image

from ..models import BBox, OcrEngineInfo, OcrPageResult, TextLine, TextWord, TextSpan


class OcrEngine(ABC):
    """A local OCR engine. Implementations must be safe to reuse across pages."""

    name: str = "base"

    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._prepared = False

    @property
    @abstractmethod
    def info(self) -> OcrEngineInfo:
        """Engine identity, version and model names."""

    @abstractmethod
    def _recognize(self, image: Image.Image) -> OcrPageResult:
        """Engine-specific inference. Called with a prepared RGB/L image."""

    def prepare(self) -> None:
        """Load models / warm up. Idempotent."""
        self._prepared = True

    def recognize(self, image: Image.Image) -> OcrPageResult:
        """Run inference and stamp latency. Errors propagate as OcrInferenceError."""
        self.prepare()
        started = time.perf_counter()
        result = self._recognize(image)
        result.latency_ms = (time.perf_counter() - started) * 1000.0
        if result.lines:
            total = sum(line.confidence or 0.0 for line in result.lines)
            result.mean_confidence = total / len(result.lines)
        return result

    def close(self) -> None:  # noqa: D102 - optional hook
        self._prepared = False


def quad_to_bbox(points: Sequence[Sequence[float]]) -> BBox:
    """Axis-aligned bounding box of a (possibly rotated) quadrilateral."""
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return BBox(min(xs), min(ys), max(xs), max(ys))


def lines_from_words(
    words: list[tuple[str, BBox, float]],
    *,
    x_tolerance: float = 12.0,
) -> list[TextLine]:
    """Group ``(text, bbox, confidence)`` words into reading-order lines.

    Used by engines that return word-level boxes (Tesseract, Vision). Grouping
    is by vertical centre overlap, then sorted left-to-right.
    """
    if not words:
        return []
    heights = [b.height for _, b, _ in words if b.height > 0]
    median_h = sorted(heights)[len(heights) // 2] if heights else 10.0
    tolerance = max(3.0, median_h * 0.5)

    ordered = sorted(words, key=lambda w: ((w[1].y0 + w[1].y1) / 2.0, w[1].x0))
    lines: list[list[tuple[str, BBox, float]]] = [[ordered[0]]]
    center = (ordered[0][1].y0 + ordered[0][1].y1) / 2.0
    for item in ordered[1:]:
        item_center = (item[1].y0 + item[1].y1) / 2.0
        if abs(item_center - center) <= tolerance:
            lines[-1].append(item)
            center = sum((b.y0 + b.y1) / 2.0 for _, b, _ in lines[-1]) / len(lines[-1])
        else:
            lines.append([item])
            center = item_center

    out: list[TextLine] = []
    for group in lines:
        group.sort(key=lambda w: w[1].x0)
        text = " ".join(text for text, _, _ in group)
        bbox = BBox(
            min(b.x0 for _, b, _ in group),
            min(b.y0 for _, b, _ in group),
            max(b.x1 for _, b, _ in group),
            max(b.y1 for _, b, _ in group),
        )
        confidence = sum(c for _, _, c in group) / len(group)
        out.append(
            TextLine(
                text=text,
                bbox=bbox,
                words=[TextWord(text=t, bbox=b, confidence=round(c, 4)) for t, b, c in group],
                spans=[TextSpan(text=text, bbox=bbox)],
                confidence=round(confidence, 4),
            )
        )
    out.sort(key=lambda line: (line.bbox.y0, line.bbox.x0))
    return out


def normalise_confidence(value: float) -> float:
    """Map engine confidence to ``[0, 1]``. Handles 0-100 and 0-1 scales."""
    value = float(value)
    if value > 1.0:
        value = value / 100.0
    return max(0.0, min(1.0, value))
