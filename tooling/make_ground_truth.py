#!/usr/bin/env python
"""Build ground-truth pages for OCR evaluation.

Two sources are supported:

``embedded``
    Uses the PDF's authored text layer for digital pages. This is the producing
    system's own string — not another OCR engine's output — so it is a valid
    reference. Lines are filtered to laboratory content and each kept line's box
    is stored, so evaluation is restricted to the table region.

``image``
    For raster-only pages: a hand-written transcription supplied as a text file.
    Nothing is auto-generated in this mode.

Usage:
    python tooling/make_ground_truth.py embedded --report <file> --pages 3,5,7
    python tooling/make_ground_truth.py image --report <file> --page 1 --text gt.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402

from mediread.config import GROUND_TRUTH_DIR, RAW_DIR  # noqa: E402
from mediread.evaluation.groundtruth import (  # noqa: E402
    GroundTruthPage,
    filter_laboratory_lines,
    is_identifying,
    looks_like_result_row,
    save_page_ground_truth,
)
from mediread.ingest.inspect import open_pdf, report_key  # noqa: E402
from mediread.ingest.structure import (  # noqa: E402
    cluster_rows,
    extract_words_exact,
    find_table_bands,
    infer_columns,
)  # noqa: E402
from mediread.evaluation.metrics import RANGE_RE, UNIT_RE  # noqa: E402
from mediread.privacy import redact_text  # noqa: E402


def build_embedded(path: Path, pages: list[int]) -> list[GroundTruthPage]:
    """Reference rows from the authored text layer, restricted to the table band.

    Rows (not raw line objects) are used because this export emits every cell as
    its own text line: row reconstruction is what an OCR engine also produces,
    so comparing rows is both fairer and closer to the product's unit of truth.
    """
    doc = open_pdf(path)
    rid = report_key(path.name)
    out: list[GroundTruthPage] = []
    try:
        for number in pages:
            page = doc[number - 1]
            rows = cluster_rows(extract_words_exact(page))
            columns, _ = infer_columns(rows) if rows else ([], 0.0)
            bands = find_table_bands(rows, columns) if columns else []
            band_indices: set[int] = set()
            if bands:
                start, end = max(bands, key=lambda b: b[1] - b[0])
                # Trim to the first table header: everything above it is page
                # furniture (patient, address, test panel) even when it shares
                # the band's geometry.
                for index in range(start, end + 1):
                    first = " ".join(w.text for w in rows[index].words)
                    if re.match(r"^\s*(?:test\s*name|investigation|parameter|test)\b", first, re.IGNORECASE):
                        start = index
                        break
                band_indices = set(range(start, end + 1))

            # Everything above the first table header is page furniture.
            header_y = None
            for row in rows:
                first = " ".join(w.text for w in row.words)
                if re.match(r"^\s*(?:test\s*name|investigation|parameter)\b", first, re.IGNORECASE):
                    header_y = row.y_center
                    break

            kept_lines: list[str] = []
            regions: list[list[float]] = []
            dropped = 0
            for index, row in enumerate(rows):
                if header_y is not None and row.y_center < header_y - 2:
                    continue
                text = " ".join(word.text for word in row.words).strip()
                if not text:
                    continue
                # Result rows are recognised by content; inside a detected table
                # band, qualitative rows ("COLOUR PALE YELLOW") are kept too
                # because they carry no number but are real results.
                in_band = index in band_indices and 2 <= len(row.words) <= 18
                identifying = is_identifying(text) or redact_text(text) != text
                if identifying or not (looks_like_result_row(text) or (in_band and not _prose(text))):
                    dropped += 1
                    continue
                kept_lines.append(text)
                regions.append(row.bbox.to_list())

            out.append(
                GroundTruthPage(
                    report_id=rid,
                    page_number=number,
                    source="embedded_text_layer",
                    provenance=(
                        "PDF authored text layer, reconstructed into table rows; "
                        f"patient metadata and non-table rows removed ({dropped} row(s)); "
                        "scoring restricted to stored row regions"
                    ),
                    lines=kept_lines,
                    exclude_patterns=[],
                    regions=regions,
                )
            )
    finally:
        doc.close()
    return out


def _prose(text: str) -> bool:
    """Explanation paragraphs are long; a row in a table band is short."""
    return len(text.split()) > 18


def build_from_text(path: Path, page_number: int, text_path: Path) -> GroundTruthPage:
    lines = [l.rstrip() for l in text_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return GroundTruthPage(
        report_id=report_key(path.name),
        page_number=page_number,
        source="hand_transcription",
        provenance=f"hand transcription of the raster image; source file {text_path.name}",
        lines=lines,
        exclude_patterns=[],
        regions=[],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p_emb = sub.add_parser("embedded")
    p_emb.add_argument("--report", required=True)
    p_emb.add_argument("--pages", required=True, help="1,3-5")
    p_img = sub.add_parser("image")
    p_img.add_argument("--report", required=True)
    p_img.add_argument("--page", type=int, required=True)
    p_img.add_argument("--text", required=True)
    args = parser.parse_args()

    path = RAW_DIR / args.report if not Path(args.report).is_absolute() else Path(args.report)
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)

    if args.mode == "embedded":
        pages: list[int] = []
        for part in args.pages.split(","):
            if "-" in part:
                a, b = part.split("-", 1)
                pages.extend(range(int(a), int(b) + 1))
            else:
                pages.append(int(part))
        for gt in build_embedded(path, pages):
            saved = save_page_ground_truth(gt)
            print(f"{saved.name}: {len(gt.lines)} lines, {len(gt.text)} chars")
    else:
        gt = build_from_text(path, args.page, Path(args.text))
        saved = save_page_ground_truth(gt)
        print(f"{saved.name}: {len(gt.lines)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
