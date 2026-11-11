"""Apple Vision text recognition (macOS, on-device).

Why it is a candidate
---------------------
* Runs entirely on the Apple Neural Engine/GPU through the system framework;
  nothing leaves the machine, no model download, no licence fee.
* Strong on dense documents and small type, and it reports per-observation
  confidence plus boxes in normalised coordinates.
* On an M2 Pro it is the fastest accurate option measured (see
  ``docs/ocr_evaluation.md``).

Constraints
-----------
* macOS-only, and it uses the OS version's model, which can change between OS
  releases. The model is therefore identified by ``OS version`` in the engine
  info so evaluation results stay reproducible.
* Apple's model is closed; it cannot be retrained and carries no clinical
  validation. It is a recognition component, not a medical device.

Language correction is **disabled**. Vision will otherwise "correct" tokens
towards dictionary words, which is precisely the silent rewriting MediRead
forbids — and it damages units such as ``µL`` and codes such as ``HbA1c``.
"""

from __future__ import annotations

import io
import platform

from PIL import Image

from ..errors import OcrInferenceError, OcrUnavailableError
from ..models import BBox, OcrEngineInfo, OcrPageResult, TextLine, TextWord, TextSpan
from .base import OcrEngine, normalise_confidence


class AppleVisionEngine(OcrEngine):
    name = "apple_vision"

    def __init__(self, language: str = "en-US", accurate: bool = True) -> None:
        super().__init__(language=language)
        self.accurate = accurate
        self._version = platform.mac_ver()[0] or "unknown"

    def prepare(self) -> None:
        if self._prepared:
            return
        try:
            import Vision  # noqa: F401
            from Foundation import NSData  # noqa: F401
            from Quartz import CGImageSourceCreateImageAtIndex  # noqa: F401
        except ImportError as exc:  # pragma: no cover - platform dependent
            raise OcrUnavailableError(
                "pyobjc Vision framework not available; "
                "install `pyobjc-framework-Vision pyobjc-framework-Quartz`"
            ) from exc
        self._prepared = True

    @property
    def info(self) -> OcrEngineInfo:
        return OcrEngineInfo(
            name=self.name,
            version=self._version,
            model="VNRecognizeTextRequest"
            + ("/accurate" if self.accurate else "/fast")
            + f"/{self.language}",
            device="ane+gpu",
            language=self.language,
            extra={"language_correction": False, "platform": "macOS"},
        )

    @staticmethod
    def _cgimage(image: Image.Image):
        from Foundation import NSData
        from Quartz import CGImageSourceCreateImageAtIndex, CGImageSourceCreateWithData

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        payload = buffer.getvalue()
        data = NSData.dataWithBytes_length_(payload, len(payload))
        source = CGImageSourceCreateWithData(data, None)
        if source is None:
            raise OcrInferenceError("cannot create image source")
        return CGImageSourceCreateImageAtIndex(source, 0, None)

    def _recognize(self, image: Image.Image) -> OcrPageResult:
        import Vision

        cg_image = self._cgimage(image.convert("RGB"))
        request = Vision.VNRecognizeTextRequest.alloc().init()
        level = (
            Vision.VNRequestTextRecognitionLevelAccurate
            if self.accurate
            else Vision.VNRequestTextRecognitionLevelFast
        )
        request.setRecognitionLevel_(level)
        request.setUsesLanguageCorrection_(False)
        try:
            request.setRecognitionLanguages_([self.language])
        except Exception:  # pragma: no cover - older macOS
            pass

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            raise OcrInferenceError(f"Vision request failed: {error}")

        results = request.results() or []
        width, height = image.width, image.height
        lines: list[TextLine] = []
        for observation in results:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            text = str(candidate.string() or "").strip()
            if not text:
                continue
            confidence = normalise_confidence(candidate.confidence())
            rect = observation.boundingBox()
            origin = rect.origin
            size = rect.size
            x0 = origin.x * width
            y1 = (1.0 - origin.y) * height
            x1 = (origin.x + size.width) * width
            y0 = (1.0 - origin.y - size.height) * height
            bbox = BBox(x0, y0, x1, y1)
            lines.append(
                TextLine(
                    text=text,
                    bbox=bbox,
                    words=_split_words(text, bbox),
                    spans=[TextSpan(text=text, bbox=bbox)],
                    confidence=round(confidence, 4),
                )
            )
        lines.sort(key=lambda line: (line.bbox.y0, line.bbox.x0))
        return OcrPageResult(
            lines=lines,
            engine=self.info,
            image_width=width,
            image_height=height,
            latency_ms=0.0,
        )


def _split_words(text: str, bbox: BBox) -> list[TextWord]:
    """Vision returns whole lines; split proportionally for downstream geometry."""
    parts = text.split()
    if len(parts) <= 1:
        return [TextWord(text=text, bbox=bbox)]
    total = sum(len(p) for p in parts) + len(parts) - 1
    char_w = bbox.width / total if total else 0.0
    words: list[TextWord] = []
    cursor = 0
    for part in parts:
        start = cursor
        cursor += len(part) + 1
        words.append(
            TextWord(
                text=part,
                bbox=BBox(bbox.x0 + start * char_w, bbox.y0, bbox.x0 + (start + len(part)) * char_w, bbox.y1),
            )
        )
    return words
