#!/usr/bin/env python
"""Reproducible OCR benchmark on the ground-truth pages.

Usage:
    python tooling/ocr_benchmark.py --engines tesseract apple_vision rapidocr
    python tooling/ocr_benchmark.py --engines tesseract --variant gray --degrade jpeg60
    python tooling/ocr_benchmark.py --compare-engines      # full matrix, writes JSON

What it measures per engine and page:

* CER / WER over the table region set in the ground truth
* numeric exact-match recall, and separate counts for decimal-point and
  digit-substitution errors
* unit-token and reference-range recall
* table-row recall (a row is matched when all of its numbers appear)
* latency per page and peak RSS delta
* engine model footprint

All inference is local. Rendered pages are labelled "rendered" in the output:
they are *not* camera photographs and results must not be read as scan/camera
robustness. The one genuine raster in the corpus (a 150 DPI page image) is
evaluated separately and labelled "raster".
"""

from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

from mediread.config import EVAL_DIR, INVENTORY_DIR, RAW_DIR  # noqa: E402
from mediread.evaluation.groundtruth import GroundTruthPage, load_all_ground_truth  # noqa: E402
from mediread.evaluation.metrics import aggregate, score_page, wilson_interval  # noqa: E402
from mediread.ingest.render import PageRaster, rasterise_page  # noqa: E402
from mediread.ingest.structure import order_lines  # noqa: E402
from mediread.models import BBox  # noqa: E402
from mediread.ocr.base import OcrEngine  # noqa: E402
from mediread.ocr.registry import create_engine  # noqa: E402


@dataclass
class PageResult:
    report_id: str
    page_number: int
    engine: str
    variant: str
    degrade: str
    rendered: bool
    latency_ms: float
    score: dict
    hypothesis_text: str = ""
    notes: list[str] = field(default_factory=list)


def load_report_map() -> dict[str, str]:
    inventory = INVENTORY_DIR / "dataset_inventory.json"
    if not inventory.exists():
        raise SystemExit("run tooling/survey_dataset.py first")
    data = json.loads(inventory.read_text())
    return {record["report_id"]: record["source_filename"] for record in data["reports"]}


def apply_degradation(image: Image.Image, mode: str) -> Image.Image:
    """Synthetic degradations. Explicitly synthetic: not a camera-photo proxy."""
    if mode == "none":
        return image
    if mode == "jpeg60":
        import io

        buffer = io.BytesIO()
        image.convert("L").save(buffer, format="JPEG", quality=60)
        buffer.seek(0)
        return Image.open(buffer).convert("L")
    if mode == "blur":
        return image.filter(ImageFilter.GaussianBlur(radius=0.8))
    if mode == "rotate1":
        return image.rotate(1.0, resample=Image.BICUBIC, fillcolor=255)
    if mode == "downscale150":
        small = image.resize((image.width // 2, image.height // 2), Image.LANCZOS)
        return small.resize(image.size, Image.LANCZOS)
    raise ValueError(f"unknown degradation {mode!r}")


def filter_to_regions(lines, regions: list[list[float]], pad: float = 2.0):
    """Keep OCR lines whose centre falls inside one of the reference regions."""
    if not regions:
        return lines
    boxes = [BBox(*r) for r in regions]
    kept = []
    for line in lines:
        cx = (line.bbox.x0 + line.bbox.x1) / 2.0
        cy = (line.bbox.y0 + line.bbox.y1) / 2.0
        for box in boxes:
            if (
                box.x0 - pad <= cx <= box.x1 + pad
                and box.y0 - pad <= cy <= box.y1 + pad
            ):
                kept.append(line)
                break
    return kept


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def peak_rss_mb() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kilobytes.
    if platform.system() == "Darwin":
        return value / (1024 * 1024)
    return value / 1024


def run_page(
    engine: OcrEngine,
    gt: GroundTruthPage,
    path: Path,
    *,
    dpi: int,
    variant: str,
    degrade: str,
) -> PageResult:
    from mediread.ingest.preprocess import apply_variant
    from mediread.ingest.pipeline import map_pixels_to_page

    doc = pymupdf.open(path)
    try:
        raster = rasterise_page(doc, gt.page_number)
        if gt.source == "hand_transcription":
            # Genuine raster page: score the embedded image itself.
            target = BBox(0, 0, doc[gt.page_number - 1].rect.width, doc[gt.page_number - 1].rect.height)
            rendered = False
            image = raster.image
        else:
            from mediread.ingest.render import render_page

            raster = render_page(doc[gt.page_number - 1], dpi=dpi)
            target = BBox(0, 0, doc[gt.page_number - 1].rect.width, doc[gt.page_number - 1].rect.height)
            rendered = True
            image = raster.image
        image = apply_variant(image, variant) if variant != "none" else image
        image = apply_degradation(image, degrade)

        started = time.perf_counter()
        result = engine.recognize(image)
        latency = (time.perf_counter() - started) * 1000.0

        lines = map_pixels_to_page(list(result.lines), raster, target)
        lines = order_lines(lines)
        if gt.source != "hand_transcription":
            lines = filter_to_regions(lines, gt.regions)
        hypothesis = "\n".join(line.text for line in lines)
        score = score_page(gt.text, hypothesis)
        return PageResult(
            report_id=gt.report_id,
            page_number=gt.page_number,
            engine=engine.name,
            variant=variant,
            degrade=degrade,
            rendered=rendered,
            latency_ms=latency,
            score=score,
            hypothesis_text=hypothesis,
        )
    finally:
        doc.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engines", nargs="+", default=["tesseract", "apple_vision", "rapidocr"])
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--variant", default="none", help="none|gray|gray_denoise|otsu|...")
    parser.add_argument("--degrade", default="none", help="none|jpeg60|blur|rotate1|downscale150")
    parser.add_argument("--out", default=str(EVAL_DIR / "ocr_results.json"))
    parser.add_argument(
        "--gt-source",
        default="embedded_text_layer",
        choices=["all", "embedded_text_layer", "hand_transcription"],
        help="restrict to one ground-truth class (default: table pages only)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    gt_pages = load_all_ground_truth()
    if args.gt_source != "all":
        gt_pages = [gt for gt in gt_pages if gt.source == args.gt_source]
    if not gt_pages:
        raise SystemExit(f"no ground truth of class {args.gt_source!r}")
    report_map = load_report_map()

    all_results: list[dict] = []
    for name in args.engines:
        engine = create_engine(name)
        try:
            engine.prepare()
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: UNAVAILABLE ({type(exc).__name__}: {exc})")
            continue
        before = peak_rss_mb()
        page_results: list[PageResult] = []
        for gt in gt_pages:
            filename = report_map.get(gt.report_id)
            if not filename:
                print(f"skip {gt.report_id}: not in inventory")
                continue
            try:
                result = run_page(
                    engine, gt, RAW_DIR / filename,
                    dpi=args.dpi, variant=args.variant, degrade=args.degrade,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {gt.report_id} p{gt.page_number}: FAILED {type(exc).__name__}: {exc}")
                continue
            page_results.append(result)

        if not page_results:
            continue
        scores = [r.score for r in page_results]
        agg = aggregate(scores)
        latencies = sorted(r.latency_ms for r in page_results)
        numeric_ref = sum(r.score["numeric"]["reference_count"] for r in page_results)
        numeric_hit = sum(r.score["numeric"]["exact_matches"] for r in page_results)
        low, high = wilson_interval(numeric_hit, numeric_ref)
        memory = peak_rss_mb() - before

        entry = {
            "engine": name,
            "engine_info": engine.info.to_dict(),
            "dpi": args.dpi,
            "variant": args.variant,
            "degrade": args.degrade,
            "gt_source": args.gt_source,
            "aggregate": agg.to_dict(),
            "numeric_exact_ci95": [round(low, 4), round(high, 4)],
            "latency_ms": {
                "mean": round(sum(latencies) / len(latencies), 1),
                "median": round(latencies[len(latencies) // 2], 1),
                "max": round(latencies[-1], 1),
            },
            "rss_delta_mb": round(memory, 1),
            "pages": [
                {
                    "report_id": r.report_id,
                    "page_number": r.page_number,
                    "rendered": r.rendered,
                    "latency_ms": round(r.latency_ms, 1),
                    "score": r.score,
                }
                for r in page_results
            ],
        }
        all_results.append(entry)

        print(
            f"\n=== {name}  ({engine.info.version})  dpi={args.dpi} "
            f"variant={args.variant} degrade={args.degrade} gt={args.gt_source}"
        )
        print(
            f"  CER={agg.cer:.3f}  WER={agg.wer:.3f}  numeric recall={agg.numeric_recall:.3f} "
            f"unit recall={agg.unit_recall:.3f}  range recall={agg.range_recall:.3f}  "
            f"(means include pages with no token of that type as 0)"
        )
        print(
            f"  decimal errors={agg.decimal_errors}  digit errors={agg.digit_errors}  "
            f"missing={agg.missing_numbers}  spurious={agg.spurious_numbers}"
        )
        print(
            f"  numeric exact {numeric_hit}/{numeric_ref} 95%CI=[{low:.3f},{high:.3f}]  "
            f"latency median={latencies[len(latencies)//2]:.0f}ms max={latencies[-1]:.0f}ms  "
            f"rss+={memory:.0f}MB"
        )
        if args.verbose:
            for r in page_results:
                s = r.score
                print(
                    f"   p{r.page_number:>3} {r.report_id[:8]} CER={s['cer']:.3f} "
                    f"num={_fmt(s['numeric']['recall'])} unit={_fmt(s['units']['recall'])} "
                    f"dec={s['numeric']['decimal_error_count']} miss={s['numeric']['missing_count']}"
                )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text()).get("runs", [])
        except json.JSONDecodeError:
            existing = []
    # Keep the latest run per (engine, dpi, variant, degrade).
    key = lambda e: (  # noqa: E731
        e["engine"], e["dpi"], e["variant"], e["degrade"], e.get("gt_source", "all")
    )
    merged = {key(e): e for e in existing}
    for entry in all_results:
        merged[key(entry)] = entry
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ground_truth_pages": len(gt_pages),
        "runs": list(merged.values()),
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nresults -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
