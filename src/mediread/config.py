"""Central configuration. Everything tunable lives here; no magic numbers in code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = PROJECT_ROOT / "medical reports"
RENDERED_DIR = DATA_DIR / "rendered"
INVENTORY_DIR = DATA_DIR / "inventory"
GROUND_TRUTH_DIR = DATA_DIR / "ground_truth"
EVAL_DIR = PROJECT_ROOT / "eval"
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
DOCS_DIR = PROJECT_ROOT / "docs"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class InspectionConfig:
    """Thresholds for page-level classification.

    Values were calibrated against the 13-report dataset (see
    docs/dataset_inventory.md) and are exposed so a future corpus can re-tune
    them without touching the classifier.
    """

    # A usable laboratory page carries far more text than this. A page whose
    # text layer is below the threshold is treated as a raster page even if a
    # stray header/footer string is present.
    min_text_chars: int = 120
    min_text_words: int = 15
    # Raster coverage above this fraction means raster content matters.
    image_cover_threshold: float = 0.30
    # A single raster covering this much of the page *is* the page body.
    full_page_image_threshold: float = 0.85
    text_cover_threshold: float = 0.02
    # Below this text coverage a page with significant raster area is mixed
    # content rather than a digital page with decorative images.
    hybrid_text_cover_threshold: float = 0.06
    grid_resolution: int = 64  # coverage sampling grid (per axis)

    # Text-integrity heuristics -------------------------------------------------
    # Below these ratios the embedded layer is probably a bad OCR artefact from
    # the producing system rather than real selectable text.
    min_alpha_ratio: float = 0.35
    min_unique_char_ratio: float = 0.03
    min_avg_word_len: float = 2.0


@dataclass(frozen=True)
class RenderConfig:
    dpi: int = _env_int("MEDIREAD_RENDER_DPI", 300)
    image_format: str = "png"
    # JPEG quality is irrelevant for PNG; kept for opt-in jpeg renders.
    jpeg_quality: int = 92
    color: bool = False  # grayscale is enough for text and 3x smaller
    alpha: bool = False


@dataclass(frozen=True)
class OcrConfig:
    engine: str = os.environ.get("MEDIREAD_OCR_ENGINE", "tesseract")
    language: str = "en"
    # Tesseract: 3 = fully automatic page segmentation, no OSD.
    tesseract_psm: int = _env_int("MEDIREAD_TESSERACT_PSM", 3)
    tesseract_oem: int = 3
    min_line_confidence: float = 0.0  # keep all tokens; consumers decide
    # Upscale small crops; OCR models expect >= ~32px text height.
    max_image_side_px: int = 4000
    preprocess: bool = True


@dataclass(frozen=True)
class IngestConfig:
    inspection: InspectionConfig = field(default_factory=InspectionConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    # When the embedded text layer is present but low quality, also run OCR and
    # keep the higher-signal result. Never silently merge the two texts.
    allow_ocr_fallback_on_bad_text: bool = True


DEFAULT_CONFIG = IngestConfig()
