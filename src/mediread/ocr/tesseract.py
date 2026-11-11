"""Tesseract 5 engine (via pytesseract + the system ``tesseract`` binary).

Why it is a candidate
---------------------
* Mature, offline, permissive (Apache-2.0), tiny footprint.
* Returns per-word boxes and confidences.
* Deterministic: the LSTM model has no sampling.

Known weaknesses on this corpus
-------------------------------
* Dense numeric tables: it sometimes merges or splits columns, and ``psm 3``
  re-orders text by detected blocks rather than by the visual grid.
* It applies a built-in dictionary in the default config; ``--psm 6`` and
  ``preserve_interword_spaces`` help, but word-level output is what we rely on,
  because downstream geometry is rebuilt from boxes, not from its text flow.

The engine is intentionally configured *without* auto-correction hints so raw
recognition is preserved.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess

from PIL import Image

from ..errors import OcrInferenceError, OcrUnavailableError
from ..models import OcrEngineInfo, OcrPageResult, TextLine
from .base import OcrEngine, lines_from_words, normalise_confidence


# Tesseract uses ISO 639-2 three-letter codes. This Homebrew build ships
# ``eng.traineddata`` and does not resolve the ``en`` alias, so the engine
# translates codes instead of failing at load time.
_LANGUAGE_ALIASES = {"en": "eng", "en-us": "eng", "en-gb": "eng"}


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(
        self, language: str = "en", psm: int = 3, oem: int = 3, tessdata_dir: str | None = None
    ) -> None:
        super().__init__(language=_LANGUAGE_ALIASES.get(language.lower(), language))
        self.psm = psm
        self.oem = oem
        self.tessdata_dir = tessdata_dir
        self._version: str | None = None
        self._tessdata: str | None = None

    def _binary(self) -> str:
        binary = shutil.which("tesseract")
        if not binary:
            raise OcrUnavailableError(
                "tesseract binary not found; install with `brew install tesseract`"
            )
        return binary

    def prepare(self) -> None:
        if self._prepared:
            return
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise OcrUnavailableError("pytesseract is not installed") from exc
        binary = self._binary()
        pytesseract.pytesseract.tesseract_cmd = binary
        self._tessdata = self.tessdata_dir or self._discover_tessdata(binary)
        try:
            self._version = str(pytesseract.get_tesseract_version())
        except Exception as exc:  # pragma: no cover
            raise OcrUnavailableError(f"cannot run tesseract: {exc}") from exc
        self._prepared = True

    @staticmethod
    def _discover_tessdata(binary: str) -> str | None:
        """Parse ``tesseract --list-langs`` for the tessdata directory."""
        try:
            completed = subprocess.run(
                [binary, "--list-langs"], capture_output=True, text=True, timeout=20, check=False
            )
        except Exception:  # pragma: no cover - defensive
            return None
        output = (completed.stdout or "") + (completed.stderr or "")
        match = re.search(r'languages in "([^"]+)"', output)
        if match:
            return match.group(1)
        candidates = [
            "/opt/homebrew/share/tessdata",
            "/usr/local/share/tessdata",
            "/usr/share/tesseract-ocr/5/tessdata",
            "/usr/share/tessdata",
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return None

    @property
    def info(self) -> OcrEngineInfo:
        return OcrEngineInfo(
            name=self.name,
            version=self._version or "unavailable",
            model=f"tessdata/{self.language} (LSTM, oem {self.oem})",
            device="cpu",
            language=self.language,
            extra={
                "psm": self.psm,
                "tessdata": self._tessdata or "",
                "platform": platform.platform(),
            },
        )

    def _recognize(self, image: Image.Image) -> OcrPageResult:
        import pytesseract
        from pytesseract import Output

        config = f"--oem {self.oem} --psm {self.psm} -c preserve_interword_spaces=1"
        if self._tessdata:
            config += f" --tessdata-dir {self._tessdata}"
        rgb = image.convert("RGB") if image.mode != "RGB" else image
        try:
            data = pytesseract.image_to_data(
                rgb, lang=self.language, config=config, output_type=Output.DICT
            )
        except Exception as exc:
            raise OcrInferenceError(f"tesseract failed: {exc}") from exc

        words: list[tuple[str, object, float]] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                confidence = normalise_confidence(data["conf"][i])
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence <= 0.0:
                continue
            from ..models import BBox

            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            words.append((text, BBox(x, y, x + w, y + h), confidence))

        lines: list[TextLine] = lines_from_words(words)  # type: ignore[arg-type]
        return OcrPageResult(
            lines=lines,
            engine=self.info,
            image_width=image.width,
            image_height=image.height,
            latency_ms=0.0,
        )
