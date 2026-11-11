"""Command-line entry point.

    mediread inspect <pdf|dir>            structural inventory (no text written)
    mediread extract <pdf|image|dir>      page extraction -> artifacts/
    mediread probe                        OCR engines available here
    mediread render <pdf> --pages 1,3-5   write page rasters for review/eval

All commands are local-only. ``extract`` writes patient text, so its output
directory must stay local; logs contain no report text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ARTIFACTS_DIR, RAW_DIR
from .ingest.inspect import document_profile, inspect_pdf
from .ingest.pipeline import IngestionPipeline, IMAGE_SUFFIXES
from .ingest.render import rasterise_page, save_raster
from .ingest.serialization import write_extraction
from .structured.pipeline import StructuredExtractionPipeline, document_from_dict
from .structured.serialization import write_results
from .ocr.registry import probe_engines
from .privacy import configure_logging


def _inputs(target: str) -> list[Path]:
    path = Path(target)
    if path.is_dir():
        files = [
            p
            for p in sorted(path.iterdir())
            if p.suffix.lower() == ".pdf" or p.suffix.lower() in IMAGE_SUFFIXES
        ]
        return files
    return [path]


def cmd_inspect(args: argparse.Namespace) -> int:
    records = []
    for path in _inputs(args.target):
        if path.suffix.lower() != ".pdf":
            continue
        stats = inspect_pdf(path)
        record = stats.to_dict()
        record["document_profile"] = document_profile(stats)
        records.append(record)
    payload = {"reports": records}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for record in records:
            print(
                f"{record['source_filename'][:20]:20s} pages={record['page_count']:>2} "
                f"profile={record['document_profile']:<8s} "
                f"classes={record['page_classes']}"
            )
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    report = probe_engines()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for name, info in report.items():
            if info.get("available"):
                print(f"{name:14s} OK    {info.get('version')}  {info.get('model')}")
            else:
                print(f"{name:14s} FAIL  {info.get('error')}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    from .ingest.inspect import open_pdf

    doc = open_pdf(args.path)
    try:
        pages = _parse_pages(args.pages, doc.page_count)
        for number in pages:
            raster = rasterise_page(doc, number)
            path = save_raster(raster, args.report_id or "render", number, suffix="_render")
            print(f"p{number:>3} -> {path} ({raster.width_px}x{raster.height_px} {raster.source} {raster.dpi}dpi)")
    finally:
        doc.close()
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    logger = configure_logging()
    out_dir = Path(args.out) if args.out else ARTIFACTS_DIR / "extractions"
    pipeline = IngestionPipeline(save_rasters=args.save_rasters)
    if args.ocr_engine:
        from .config import IngestConfig, InspectionConfig, OcrConfig, RenderConfig

        pipeline.cfg = IngestConfig(
            inspection=InspectionConfig(),
            render=RenderConfig(dpi=args.dpi),
            ocr=OcrConfig(engine=args.ocr_engine, language=args.lang),
        )

    failures = 0
    for path in _inputs(args.target):
        try:
            if path.suffix.lower() in IMAGE_SUFFIXES:
                outcome = pipeline.process_image(path)
            else:
                outcome = pipeline.process_pdf(path, ocr=not args.no_ocr, pages=_parse_pages(args.pages, None))
        except Exception as exc:  # noqa: BLE001 - reported to the operator
            logger.error("%s: %s", path.name, f"{type(exc).__name__}: {exc}")
            failures += 1
            continue
        doc = outcome.document
        digest = (outcome.inspection or {}).get("sha256")
        if not digest:
            from .ingest.inspect import sha256_file

            digest = sha256_file(path)
        paths = write_extraction(
            doc,
            out_dir,
            include_lines=not args.no_boxes,
            config={
                "dpi": args.dpi,
                "ocr": not args.no_ocr,
                "engine": args.ocr_engine or pipeline.cfg.ocr.engine,
            },
            source_sha256=digest,
        )
        embedded = doc.engine_summary.get("embedded_text_pages", 0)
        ocr_pages = doc.engine_summary.get("ocr_pages", 0)
        hybrid = doc.engine_summary.get("hybrid_pages", 0)
        print(
            f"{path.name[:24]:24s} pages={doc.page_count:>2} embedded={embedded:>2} "
            f"ocr={ocr_pages:>2} hybrid={hybrid:>2} "
            f"warnings={len(doc.warnings):>2} -> {paths[0].name}"
        )
    return 1 if failures else 0


def cmd_results(args: argparse.Namespace) -> int:
    """Run structured extraction on extraction artefacts (or a PDF/image)."""
    logger = configure_logging()
    out_dir = Path(args.out) if args.out else ARTIFACTS_DIR / "results"
    pipeline = StructuredExtractionPipeline()
    target = Path(args.target)
    if target.is_dir():
        inputs = [
            p for p in sorted(target.glob("*.json"))
            if not p.name.endswith(".run.json")
        ]
    else:
        inputs = [target]
    failures = 0
    for path in inputs:
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                from .ingest.pipeline import IngestionPipeline

                outcome = IngestionPipeline().process_pdf(path)
                payload = outcome.document.to_dict() if hasattr(outcome.document, "to_dict") else None
                if payload is None:
                    from .ingest.serialization import document_payload

                    payload = document_payload(outcome.document)
                payload["pages"] = payload.get("pages", [])
            document = pipeline.process(payload, pages=_parse_pages(args.pages, None))
        except Exception as exc:  # noqa: BLE001 - operator-facing
            logger.error("%s: %s", path.name, f"{type(exc).__name__}: {exc}")
            failures += 1
            continue
        saved = write_results(document, out_dir, config={"pages": args.pages})
        stats = document.stats
        print(
            f"{document.report_id[:24]:24s} results={len(document.results):>3} "
            f"verified={stats['verified_results']:>3} review={stats['review_results']:>2} "
            f"unparsed={stats['unparsed_rows']:>2} -> {saved.name}"
        )
        if args.summary:
            for result in document.results:
                mark = "!" if result.status.value != "verified" else " "
                print(
                    f" {mark} p{result.page:>2} {result.test.raw[:36]:36s} "
                    f"{str(result.value.raw)[:12]:12s} {str(result.unit.raw)[:10]:10s} "
                    f"{str(result.reference.raw)[:24]:24s} [{result.status.value}]"
                )
    return 1 if failures else 0


def _parse_pages(spec: str | None, page_count: int | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mediread", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="structural inventory of PDFs")
    p_inspect.add_argument("target", help="PDF file or directory")
    p_inspect.add_argument("--json", action="store_true")
    p_inspect.set_defaults(func=cmd_inspect)

    p_extract = sub.add_parser("extract", help="extract pages to JSON artefacts")
    p_extract.add_argument("target", help="PDF/image file or directory")
    p_extract.add_argument("--out", help="output directory")
    p_extract.add_argument("--ocr-engine", help="tesseract | apple_vision | rapidocr | paddleocr")
    p_extract.add_argument("--lang", default="en")
    p_extract.add_argument("--dpi", type=int, default=300)
    p_extract.add_argument("--pages", help="page selection, e.g. 1,4-6")
    p_extract.add_argument("--no-ocr", action="store_true", help="embedded text only")
    p_extract.add_argument("--no-boxes", action="store_true", help="omit line/word boxes")
    p_extract.add_argument("--save-rasters", action="store_true")
    p_extract.set_defaults(func=cmd_extract)

    p_results = sub.add_parser("results", help="structured laboratory results")
    p_results.add_argument("target", help="extraction JSON, PDF/image file or directory")
    p_results.add_argument("--out", help="output directory")
    p_results.add_argument("--pages", help="page selection, e.g. 1,4-6")
    p_results.add_argument("--summary", action="store_true", help="print one line per result")
    p_results.set_defaults(func=cmd_results)

    p_probe = sub.add_parser("probe", help="report OCR engine availability")
    p_probe.add_argument("--json", action="store_true")
    p_probe.set_defaults(func=cmd_probe)

    p_render = sub.add_parser("render", help="write page rasters")
    p_render.add_argument("path")
    p_render.add_argument("--pages", help="e.g. 1,4-6")
    p_render.add_argument("--report-id", help="subdirectory name")
    p_render.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
