"""Export per-character glyph geometry from a PDF for the Dart table parser.

The Flutter extraction path (``app/lib/src/ingest/pdf_table_source.dart``) reads
pdfium character rectangles through pdfrx, in text order, with a top-down y axis.
pdfium cannot load inside ``flutter test`` on the host, so this script captures
the same information once with PyMuPDF and writes it as JSON. The Dart test then
replays the *real* layout through ``TableParser`` on the host.

Coordinate conventions match pdfrx after the y flip in ``pdf_table_source.dart``:

* origin top-left, y grows downward, units are PDF points at scale 1.0
* characters arrive in reading order
* a line ends with a zero-area ``\\n`` glyph (pdfium emits ``\\r\\n`` the same way)
* spaces are explicit glyphs with a real width

The output contains text copied from the report it was built from, including
patient identifiers. Write it under ``.cache/`` (git-ignored) and never commit it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf


def _line_chars(line: dict) -> list[tuple[str, tuple[float, float, float, float]]]:
    chars: list[tuple[str, tuple[float, float, float, float]]] = []
    for span in line["spans"]:
        for char in span.get("chars", []):
            chars.append((char["c"], tuple(round(v, 2) for v in char["bbox"])))
    return chars


def _with_spaces(line: dict) -> list[list]:
    """Emit glyph arrays ``[text, x0, y0, x1, y1]`` for one text line.

    PyMuPDF usually reports explicit space glyphs, but when a PDF positions words
    with horizontal offsets instead of space characters they are missing. pdfium
    inserts a space at such gaps, so derive one from the geometry; otherwise the
    Dart word builder would merge neighbouring words.
    """
    chars = _line_chars(line)
    x0, y0, x1, y1 = (round(v, 2) for v in line["bbox"])
    height = max(1.0, y1 - y0)
    glyphs: list[list] = []
    previous_right: float | None = None
    previous_char = ""

    for char, bbox in chars:
        left, top, right, bottom = bbox
        if previous_right is not None and char.strip() and previous_char.strip():
            gap = left - previous_right
            if gap > 0.22 * height:
                glyphs.append([" ", round(previous_right, 2), y0,
                               round(left, 2), y1])
        glyphs.append([char, left, top, right, bottom])
        previous_right = right if previous_right is None else max(previous_right, right)
        previous_char = char

    glyphs.append(["\n", x1, y0, x1, y0])
    return glyphs


def export(pdf_path: Path, page_numbers: list[int] | None = None) -> dict:
    document = pymupdf.open(pdf_path)
    pages: list[list[dict]] = []
    sizes: list[list[float]] = []
    for page_index in range(document.page_count):
        if page_numbers and (page_index + 1) not in page_numbers:
            pages.append([])
            sizes.append([round(document[page_index].rect.width, 2),
                          round(document[page_index].rect.height, 2)])
            continue
        page = document[page_index]
        sizes.append([round(page.rect.width, 2), round(page.rect.height, 2)])
        glyphs: list[dict] = []
        data = page.get_text("rawdict")
        # Blocks arrive in reading order; lines within a block are ordered too.
        for block in data["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                try:
                    glyphs.extend(_with_spaces(line))
                except ValueError:
                    # A line we cannot align is skipped rather than guessed at.
                    continue
        pages.append(glyphs)
    document.close()
    return {
        "_note": "derived from a patient report; local-only, contains identifiers",
        "source": hashlib.sha256(pdf_path.name.encode()).hexdigest()[:16],
        "fileName": pdf_path.name,
        "pageSizes": sizes,
        "pages": pages,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="*", default=None)
    args = parser.parse_args()

    fixture = export(args.pdf, args.pages)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, separators=(",", ":")))
    glyphs = sum(len(page) for page in fixture["pages"])
    print(f"wrote {args.out} ({glyphs} glyphs, {len(fixture['pages'])} pages, "
          f"{args.out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
