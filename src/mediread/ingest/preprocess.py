"""Image preprocessing for OCR.

Everything here is optional and measurable. Tesseract and Vision both binarise
internally, so aggressive preprocessing frequently *reduces* accuracy on clean
150-300 DPI laboratory exports. The defaults are therefore conservative
(grayscale + mild denoise), and ``eval/ocr_benchmark.py`` records the effect of
each variant on the same pages so the choice is evidence-based rather than a
matter of taste.

No step here alters content: deskew rotates, denoise smooths, binarise
thresholds. None of them rewrite text.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def to_grayscale(image: Image.Image) -> Image.Image:
    if image.mode == "L":
        return image
    return ImageOps.grayscale(image)


def denoise(image: Image.Image, radius: int = 1) -> Image.Image:
    """Median filter: removes salt-and-pepper scanning noise, keeps edges."""
    if radius <= 0:
        return image
    return image.filter(ImageFilter.MedianFilter(size=radius * 2 + 1))


def estimate_skew(image: Image.Image, max_angle: float = 4.0, step: float = 0.4) -> float:
    """Estimate page skew in degrees from the variance of row ink projections.

    A correctly aligned text page has sharp horizontal ink profiles; rotating
    the image by the wrong angle blurs them. This is the standard projection
    profile method and costs a few tens of milliseconds at 150-300 DPI.
    """
    gray = to_grayscale(image)
    # Downscale for speed; skew is a global property.
    scale = min(1.0, 900.0 / max(gray.width, 1))
    small = gray.resize((max(1, int(gray.width * scale)), max(1, int(gray.height * scale))))
    best_angle = 0.0
    best_score = -1.0
    angle = -max_angle
    while angle <= max_angle + 1e-9:
        rotated = small.rotate(angle, resample=Image.BILINEAR, fillcolor=255)
        array = np.asarray(rotated, dtype=np.float32)
        ink = 255.0 - array
        profile = ink.sum(axis=1)
        score = float(np.var(np.diff(profile)))
        if score > best_score:
            best_score = score
            best_angle = angle
        angle += step
    return best_angle


def deskew(image: Image.Image, max_angle: float = 4.0) -> tuple[Image.Image, float]:
    """Rotate to remove skew. Returns the image and the applied angle."""
    angle = estimate_skew(image, max_angle=max_angle)
    if abs(angle) < 0.3:
        return image, 0.0
    return image.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor=255), angle


def binarize(image: Image.Image, method: str = "otsu") -> Image.Image:
    """Global Otsu threshold. Kept for evaluation, not enabled by default."""
    gray = np.asarray(to_grayscale(image), dtype=np.uint8)
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = gray.size
    sum_all = np.dot(np.arange(256), histogram)
    weight_bg = np.cumsum(histogram)
    weight_fg = total - weight_bg
    sum_bg = np.cumsum(np.arange(256) * histogram)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_all - sum_bg) / weight_fg
        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
    variance = np.nan_to_num(variance)
    threshold = int(np.argmax(variance)) if method == "otsu" else 127
    binary = np.where(gray > threshold, 255, 0).astype(np.uint8)
    return Image.fromarray(binary, mode="L")


def upscale_if_small(image: Image.Image, min_height_px: int = 1200) -> Image.Image:
    """Upscale very small crops so the recogniser sees enough pixels per glyph.

    Only ever upscales; never downscales a document (downscaling destroys the
    small superscripts used in units such as ``10³``).
    """
    if image.height >= min_height_px:
        return image
    factor = min_height_px / max(image.height, 1)
    return image.resize(
        (int(image.width * factor), int(image.height * factor)), Image.LANCZOS
    )


PREPROCESS_VARIANTS = {
    "none": lambda image: image,
    "gray": to_grayscale,
    "gray_denoise": lambda image: denoise(to_grayscale(image), 1),
    "gray_deskew": lambda image: deskew(to_grayscale(image))[0],
    "otsu": lambda image: binarize(to_grayscale(image)),
    "gray_denoise_otsu": lambda image: binarize(denoise(to_grayscale(image), 1)),
}


def apply_variant(image: Image.Image, variant: str) -> Image.Image:
    """Apply a named preprocessing variant (see ``PREPROCESS_VARIANTS``)."""
    try:
        function = PREPROCESS_VARIANTS[variant]
    except KeyError as exc:
        raise ValueError(f"unknown preprocessing variant {variant!r}") from exc
    return function(image)
