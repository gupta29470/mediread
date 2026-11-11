"""RapidOCR (PP-OCR family models executed on ONNX Runtime).

PP-OCR is the recognition stack behind PaddleOCR. RapidOCR packages the same
pretrained detection/recognition models for ONNX Runtime, which avoids the
heavy PaddlePaddle runtime and works natively on Apple Silicon CPU (and, with
``onnxruntime`` GPU builds, elsewhere).

Model/licence posture
---------------------
* Code: Apache-2.0 (RapidOCR).
* Models: PP-OCRv4/v5 detection + recognition weights, Apache-2.0.
* Fully offline after the first model resolution; models are small (~15 MB).

Trade-off: no Apple ANE acceleration, so it is slower than Apple Vision on this
hardware, and it returns line-level boxes rather than word boxes. Word geometry
is reconstructed proportionally exactly as for Vision.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from ..errors import OcrInferenceError, OcrUnavailableError
from ..models import BBox, OcrEngineInfo, OcrPageResult, TextLine
from .base import OcrEngine, normalise_confidence, quad_to_bbox
from .vision import _split_words


class RapidOcrEngine(OcrEngine):
    name = "rapidocr"

    def __init__(self, language: str = "en", det_limit_side_len: int = 1600) -> None:
        super().__init__(language=language)
        self.det_limit_side_len = det_limit_side_len
        self._engine = None
        self._version = "unknown"
        self._model = "PP-OCR (det+rec, ONNX)"

    def prepare(self) -> None:
        if self._prepared:
            return
        try:
            import rapidocr_onnxruntime
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OcrUnavailableError(
                "rapidocr-onnxruntime is not installed; `pip install rapidocr-onnxruntime`"
            ) from exc
        try:
            from importlib.metadata import version as _pkg_version

            self._version = _pkg_version("rapidocr-onnxruntime")
        except Exception:  # pragma: no cover
            self._version = getattr(rapidocr_onnxruntime, "__version__", "unknown")
        try:
            self._engine = rapidocr_onnxruntime.RapidOCR()
        except Exception as exc:  # pragma: no cover
            raise OcrUnavailableError(f"cannot initialise RapidOCR: {exc}") from exc
        self._prepared = True

    @property
    def info(self) -> OcrEngineInfo:
        return OcrEngineInfo(
            name=self.name,
            version=self._version,
            model=self._model,
            device="cpu",
            language=self.language,
            extra={"runtime": "onnxruntime", "det_limit_side_len": self.det_limit_side_len},
        )

    def _recognize(self, image: Image.Image) -> OcrPageResult:
        array = np.asarray(image.convert("RGB"))
        try:
            output = self._engine(array)
        except Exception as exc:
            raise OcrInferenceError(f"RapidOCR failed: {exc}") from exc

        entries = _normalise_output(output)
        lines: list[TextLine] = []
        for box, text, score in entries:
            text = (text or "").strip()
            if not text:
                continue
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


def _normalise_output(output) -> list[tuple[list, str, float]]:
    """Accept both RapidOCR <=1.4 tuple output and 2.x result objects."""
    entries: list[tuple[list, str, float]] = []

    if isinstance(output, tuple) and len(output) == 2:
        result = output[0]
        if result:
            for item in result:
                if len(item) >= 3:
                    entries.append((item[0], item[1], item[2]))
        return entries

    # 2.x: object with .boxes, .txts, .scores
    boxes = getattr(output, "boxes", None)
    txts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if boxes is not None and txts is not None:
        for box, text, score in zip(boxes, txts, scores or [0.0] * len(txts)):
            entries.append((list(box), text, float(score)))
    return entries
