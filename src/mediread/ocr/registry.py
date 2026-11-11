"""OCR engine registry.

Engines are resolved by name and imported lazily so that installing MediRead
without any OCR backend still works (the digital-PDF path needs none).
"""

from __future__ import annotations

import importlib
from typing import Callable

from ..errors import OcrUnavailableError
from .base import OcrEngine

_BUILDERS: dict[str, Callable[..., OcrEngine]] = {}


def register(name: str) -> Callable[[Callable[..., OcrEngine]], Callable[..., OcrEngine]]:
    def decorator(builder: Callable[..., OcrEngine]) -> Callable[..., OcrEngine]:
        _BUILDERS[name] = builder
        return builder

    return decorator


def _tesseract(**kwargs) -> OcrEngine:
    from .tesseract import TesseractEngine

    return TesseractEngine(**kwargs)


def _rapidocr(**kwargs) -> OcrEngine:
    from .rapidocr import RapidOcrEngine

    return RapidOcrEngine(**kwargs)


def _vision(**kwargs) -> OcrEngine:
    from .vision import AppleVisionEngine

    return AppleVisionEngine(**kwargs)


def _paddle(**kwargs) -> OcrEngine:
    from .paddle import PaddleOcrEngine

    return PaddleOcrEngine(**kwargs)


_BUILDERS.update(
    {"tesseract": _tesseract, "rapidocr": _rapidocr, "apple_vision": _vision, "paddleocr": _paddle}
)

AVAILABLE_ENGINES = tuple(sorted(_BUILDERS))


def create_engine(name: str, **kwargs) -> OcrEngine:
    """Instantiate an engine by name. Raises OcrUnavailableError for unknown names."""
    try:
        builder = _BUILDERS[name]
    except KeyError as exc:
        raise OcrUnavailableError(
            f"unknown OCR engine {name!r}; available: {', '.join(AVAILABLE_ENGINES)}"
        ) from exc
    return builder(**kwargs)


def probe_engines() -> dict[str, dict[str, str | bool]]:
    """Report which engines can actually run in this environment."""
    report: dict[str, dict[str, str | bool]] = {}
    for name in AVAILABLE_ENGINES:
        try:
            engine = create_engine(name)
            engine.prepare()
            info = engine.info
            report[name] = {
                "available": True,
                "version": info.version,
                "model": info.model or "",
                "device": info.device,
            }
        except Exception as exc:  # noqa: BLE001 - diagnostic surface
            report[name] = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
    return report
