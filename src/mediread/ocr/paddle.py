"""PaddleOCR (PP-OCR) engine.

Included because it is the most widely used open OCR stack and the reference
implementation of the PP-OCR models that RapidOCR packages. It is *not* the
default: the PaddlePaddle runtime is a large dependency, its macOS wheels are
platform-sensitive, and its inference API has changed across 2.x/3.x.
Both APIs are handled below so the integration does not pin a single release.

Licensing: PaddleOCR code Apache-2.0, PP-OCR models Apache-2.0.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from ..errors import OcrInferenceError, OcrUnavailableError
from ..models import OcrEngineInfo, OcrPageResult, TextLine
from .base import OcrEngine, normalise_confidence, quad_to_bbox
from .vision import _split_words


def _parse_result(page) -> list[tuple[list, str, float]]:
    """Normalise a 3.x OCRResult (or plain dict) into (box, text, score) tuples."""
    data = page.json.get("res", page.json) if hasattr(page, "json") else page
    if not isinstance(data, dict):
        return []
    texts = data.get("rec_texts") or []
    scores = data.get("rec_scores") or [0.0] * len(texts)
    boxes = data.get("rec_boxes") or data.get("rec_polys") or []
    out: list[tuple[list, str, float]] = []
    for index, text in enumerate(texts):
        if index >= len(boxes):
            break
        box = boxes[index]
        score = float(scores[index]) if index < len(scores) else 0.0
        out.append((list(box), text, score))
    return out


class PaddleOcrEngine(OcrEngine):
    name = "paddleocr"

    def __init__(self, language: str = "en", use_angle_cls: bool = True) -> None:
        super().__init__(language=language)
        self.use_angle_cls = use_angle_cls
        self._engine = None
        self._version = "unknown"
        self._api = "unknown"

    def prepare(self) -> None:
        if self._prepared:
            return
        # PaddleX writes models and config under ``~/.paddlex`` by default, which
        # fails in sandboxes and inside packaged apps. Redirect to a project
        # cache before importing paddleocr.
        if not os.environ.get("PADDLE_PDX_CACHE_HOME"):
            cache = Path.cwd() / ".cache" / "paddlex"
            cache.mkdir(parents=True, exist_ok=True)
            os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache)
        try:
            import paddleocr
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OcrUnavailableError(
                "paddleocr is not installed; `pip install paddlepaddle paddleocr`"
            ) from exc
        self._version = getattr(paddleocr, "__version__", "unknown")
        try:
            self._engine = paddleocr.PaddleOCR(
                lang=self.language,
                use_angle_cls=self.use_angle_cls,
                show_log=False,
            )
            self._api = "ocr"
        except (TypeError, ValueError):
            # 3.x removed use_angle_cls/show_log and rejects unknown kwargs.
            try:
                self._engine = paddleocr.PaddleOCR(lang=self.language)
                self._api = "predict"
            except Exception as exc:  # pragma: no cover
                raise OcrUnavailableError(f"cannot initialise PaddleOCR: {exc}") from exc
        except Exception as exc:  # pragma: no cover
            raise OcrUnavailableError(f"cannot initialise PaddleOCR: {exc}") from exc
        self._prepared = True

    @property
    def info(self) -> OcrEngineInfo:
        models = ""
        try:  # 3.x exposes the resolved model names on the pipeline
            names = []
            for attribute in ("text_det_model_name", "text_rec_model_name"):
                value = getattr(self._engine, attribute, None)
                if not value:
                    pipeline = getattr(self._engine, "_pipeline", None)
                    value = getattr(pipeline, attribute, None) if pipeline else None
                if value:
                    names.append(str(value))
            models = ", ".join(names)
        except Exception:  # pragma: no cover
            pass
        return OcrEngineInfo(
            name=self.name,
            version=self._version,
            model=models or "PP-OCR det+rec (paddle)",
            device="cpu",
            language=self.language,
            extra={"api": self._api, "use_angle_cls": self.use_angle_cls},
        )

    def _run(self, array: np.ndarray) -> list[tuple[list, str, float]]:
        entries: list[tuple[list, str, float]] = []
        try:
            if self._api == "ocr":
                raw = self._engine.ocr(array, cls=self.use_angle_cls)
                for page in raw or []:
                    for item in page or []:
                        box, (text, score) = item[0], item[1]
                        entries.append((list(box), text, float(score)))
            else:
                raw = self._engine.predict(array)
                for page in raw or []:
                    entries.extend(_parse_result(page))
        except Exception as exc:
            raise OcrInferenceError(f"PaddleOCR failed: {exc}") from exc
        return entries

    def _recognize(self, image: Image.Image) -> OcrPageResult:
        array = np.asarray(image.convert("RGB"))
        lines: list[TextLine] = []
        for box, text, score in self._run(array):
            text = (text or "").strip()
            if not text:
                continue
            if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                from ..models import BBox

                bbox = BBox(*[float(v) for v in box])
            else:
                bbox = quad_to_bbox(box)
            confidence = normalise_confidence(score)
            lines.append(
                TextLine(
                    text=text,
                    bbox=bbox,
                    words=_split_words(text, bbox),
                    confidence=round(confidence, 4),
                )
            )
        lines.sort(key=lambda line: (line.bbox.y0, line.bbox.x0))
        return OcrPageResult(
            lines=lines,
            engine=self.info,
            image_width=image.width,
            image_height=image.height,
            latency_ms=0.0,
        )
