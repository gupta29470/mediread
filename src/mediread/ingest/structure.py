"""Direct (embedded) text extraction with geometry, and table-structure probing.

The corpus is produced by a laboratory information system (iTextSharp export).
Its tables are **not** drawn with vector rules: cells are positioned by
whitespace only. "Text extraction succeeded" therefore cannot be established by
looking at the extracted string — the only honest test is whether word geometry
still clusters into stable columns and rows.

A second finding drove the design here. PyMuPDF's layout-model table finder
(``page.find_tables()``, backed by ``pymupdf_layout`` ONNX models) was evaluated
on these pages and **silently corrupted numeric cells**::

    65.63  ->  '65 63\\n.'      45-129 -> '45 129\\n-'

A moved decimal point is a wrong laboratory value. MediRead therefore never
lets a layout model re-segment characters. Column geometry is inferred here from
a text-projection profile over *verbatim* word tokens, so every character and
every decimal point comes from the PDF's own text layer.

This module provides:

* :func:`extract_lines` — faithful text with word-level boxes (provenance).
* :func:`cluster_rows` — y-clustering of words into visual rows.
* :func:`infer_columns` — x-projection profile → column boundaries.
* :func:`measure_table_structure` — quantitative evidence for the inventory.

No text is corrected, reordered or rewritten here; only grouped.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field

import pymupdf

from ..models import BBox, TextLine, TextSpan, TextWord


@dataclass
class Row:
    """A visual row of words, ordered left-to-right."""

    y_center: float
    words: list[TextWord]
    segments: int = 0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> BBox:
        return BBox(
            min(w.bbox.x0 for w in self.words),
            min(w.bbox.y0 for w in self.words),
            max(w.bbox.x1 for w in self.words),
            max(w.bbox.y1 for w in self.words),
        )


@dataclass
class Column:
    index: int
    x0: float
    x1: float

    def contains(self, x: float) -> bool:
        return self.x0 <= x < self.x1


@dataclass
class TableProbe:
    """Result of probing one page for a whitespace-aligned table."""

    row_count: int
    column_count: int
    table_row_count: int          # rows split into >= 3 column bands
    modal_segment_count: int      # most common band count among table rows
    segment_consistency: float    # share of table rows matching that count
    median_row_gap_pt: float
    usable: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        from dataclasses import asdict

        return asdict(self)


def extract_lines(page: pymupdf.Page) -> list[TextLine]:
    """Extract text lines with word boxes, spans and font metadata.

    ``sort=True`` asks MuPDF for reading order; the result is re-sorted by
    (y, x) because MuPDF occasionally emits labels out of order on these pages.
    """
    data = page.get_text("dict", sort=True)
    lines: list[TextLine] = []
    for block in data.get("blocks", ()):
        if block.get("type") != 0:
            continue
        for raw_line in block.get("lines", ()):
            spans: list[TextSpan] = []
            words: list[TextWord] = []
            for span in raw_line.get("spans", ()):
                text = span.get("text", "")
                if not text:
                    continue
                bbox = BBox.from_list(span["bbox"])
                spans.append(
                    TextSpan(
                        text=text,
                        bbox=bbox,
                        font=span.get("font"),
                        size=round(float(span["size"]), 2) if span.get("size") else None,
                    )
                )
                words.extend(_split_span_words(text, bbox))
            if not spans:
                continue
            text = "".join(s.text for s in spans)
            lines.append(
                TextLine(
                    text=text,
                    bbox=BBox.from_list(raw_line["bbox"]),
                    words=words,
                    spans=spans,
                )
            )
    lines.sort(key=lambda line: (round(line.bbox.y0, 1), line.bbox.x0))
    return lines


def _split_span_words(text: str, bbox: BBox) -> list[TextWord]:
    """Split a span into words, interpolating boxes by character width.

    MuPDF exposes per-character boxes via "rawdict"; interpolating from the
    span box keeps output compact while remaining accurate to well under one
    character for these monospaced-ish report fonts. Exact boxes are available
    through :func:`extract_words_exact`, which the pipeline uses for
    row/column geometry.
    """
    parts = text.split(" ")
    if len(parts) == 1:
        return [TextWord(text=text, bbox=bbox)]
    total = len(text)
    if total == 0 or bbox.width <= 0:
        return [TextWord(text=w, bbox=bbox) for w in parts if w]

    char_w = bbox.width / total
    out: list[TextWord] = []
    cursor = 0
    for part in parts:
        start = cursor
        cursor += len(part) + 1
        if not part:
            continue
        x0 = bbox.x0 + start * char_w
        x1 = bbox.x0 + (start + len(part)) * char_w
        out.append(TextWord(text=part, bbox=BBox(x0, bbox.y0, x1, bbox.y1)))
    return out


def extract_words_exact(page: pymupdf.Page) -> list[TextWord]:
    """Exact per-word boxes from MuPDF's word extractor."""
    return [
        TextWord(text=w[4], bbox=BBox(float(w[0]), float(w[1]), float(w[2]), float(w[3])))
        for w in page.get_text("words", sort=True)
    ]


def cluster_rows(words: list[TextWord], y_factor: float = 0.55) -> list[Row]:
    """Group words into visual rows using vertical overlap of word boxes.

    Two words belong to the same row when their vertical centres fall within
    ``y_factor`` × median word height. This tolerates the 1-2 pt baseline
    jitter in these exports without merging adjacent test rows (row pitch is
    ~12 pt, word height ~8.9 pt).
    """
    if not words:
        return []
    heights = [w.bbox.height for w in words if w.bbox.height > 0]
    median_h = statistics.median(heights) if heights else 8.0
    tolerance = max(2.0, median_h * y_factor)

    ordered = sorted(words, key=lambda w: ((w.bbox.y0 + w.bbox.y1) / 2.0, w.bbox.x0))
    groups: list[list[TextWord]] = []
    current: list[TextWord] = [ordered[0]]
    current_center = (ordered[0].bbox.y0 + ordered[0].bbox.y1) / 2.0

    for word in ordered[1:]:
        center = (word.bbox.y0 + word.bbox.y1) / 2.0
        if abs(center - current_center) <= tolerance:
            current.append(word)
            current_center = sum((w.bbox.y0 + w.bbox.y1) / 2.0 for w in current) / len(current)
        else:
            groups.append(current)
            current = [word]
            current_center = center
    groups.append(current)

    rows: list[Row] = []
    for group in groups:
        group.sort(key=lambda w: w.bbox.x0)
        y_center = sum((w.bbox.y0 + w.bbox.y1) / 2.0 for w in group) / len(group)
        rows.append(Row(y_center=y_center, words=group))
    rows.sort(key=lambda r: r.y_center)
    return rows


def gap_threshold(
    rows: list[Row], *, gap_factor: float = 3.0, min_gap_pt: float = 10.0
) -> float:
    """A word-gap above this value separates cells rather than words.

    Must be derived from *all* rows on the page: inside a table band every gap is
    a column gap, so the median would jump to ~60 pt and the adaptive threshold
    would then reject every real boundary.
    """
    gaps = sorted(
        right.bbox.x0 - left.bbox.x1
        for row in rows
        for left, right in zip(row.words, row.words[1:])
        if right.bbox.x0 - left.bbox.x1 > 0
    )
    if not gaps:
        return min_gap_pt
    # The lower quartile, not the median: a sparse page (few prose lines) can
    # have more cell gaps than word gaps, and the median would then exceed every
    # real column boundary.
    lower_quartile = gaps[len(gaps) // 4]
    return max(min_gap_pt, gap_factor * lower_quartile)


def order_lines(lines: list[TextLine], y_factor: float = 0.6) -> list[TextLine]:
    """Reconstruct reading order from geometry.

    OCR engines emit one observation per text run. Inside a ruled table the
    test name, value, unit and range of the same row are separate observations
    whose boxes differ vertically by a few points (ascender vs baseline), so
    sorting by ``y0`` alone interleaves rows and destroys the table. Grouping by
    vertical centre and then ordering left-to-right within the group restores
    row order for every engine.
    """
    if len(lines) <= 1:
        return list(lines)
    heights = [line.bbox.height for line in lines if line.bbox.height > 0]
    median_h = statistics.median(heights) if heights else 10.0
    tolerance = max(2.0, median_h * y_factor)

    ordered = sorted(lines, key=lambda l: ((l.bbox.y0 + l.bbox.y1) / 2.0, l.bbox.x0))
    rows: list[list[TextLine]] = [[ordered[0]]]
    center = (ordered[0].bbox.y0 + ordered[0].bbox.y1) / 2.0
    for line in ordered[1:]:
        line_center = (line.bbox.y0 + line.bbox.y1) / 2.0
        if abs(line_center - center) <= tolerance:
            rows[-1].append(line)
            center = statistics.fmean((l.bbox.y0 + l.bbox.y1) / 2.0 for l in rows[-1])
        else:
            rows.append([line])
            center = line_center

    out: list[TextLine] = []
    for row in rows:
        row.sort(key=lambda l: l.bbox.x0)
        out.extend(row)
    return out


def infer_columns(
    rows: list[Row],
    *,
    gap_factor: float = 3.0,
    min_gap_pt: float = 10.0,
    boundary_tolerance_pt: float = 6.0,
    min_row_support: float = 0.05,
    threshold: float | None = None,
) -> tuple[list[Column], float]:
    """Infer column bands from horizontal whitespace between words.

    The gap distribution in this corpus is strongly bimodal: 2-3 pt inside a
    cell (word spacing) and 22-190 pt between columns. A gap threshold of
    ``max(min_gap_pt, gap_factor * median_gap)`` separates the two modes without
    hard-coding a laboratory's layout.

    Per-row boundaries (the start of each cell after a wide gap) are then
    clustered across rows, and the layout signature supported by the most rows is
    selected. This rejects accidental wide gaps inside a single long header line
    and tolerates columns that are not perfectly aligned.

    Returns the columns and the median intra-row gap in points.
    """
    if not rows:
        return [], 0.0

    per_row_gaps: list[list[float]] = []
    all_gaps: list[float] = []
    for row in rows:
        gaps: list[float] = []
        for left, right in zip(row.words, row.words[1:]):
            gap = right.bbox.x0 - left.bbox.x1
            gaps.append(gap)
            if gap > 0:
                all_gaps.append(gap)
        per_row_gaps.append(gaps)

    if not all_gaps:
        return [], 0.0

    median_gap = statistics.median(all_gaps)
    if threshold is None:
        threshold = gap_threshold(rows, gap_factor=gap_factor, min_gap_pt=min_gap_pt)

    per_row_boundaries: list[list[float]] = []
    for row, gaps in zip(rows, per_row_gaps):
        boundaries: list[float] = []
        for (left, right), gap in zip(zip(row.words, row.words[1:]), gaps):
            if gap >= threshold:
                # Use the start of the next cell, not the midpoint of the gap:
                # cell starts are left-aligned by the producing system and are
                # therefore stable across rows, while a midpoint moves with the
                # width of the value ("9.9" vs "136.17").
                boundaries.append(right.bbox.x0)
        per_row_boundaries.append(boundaries)

    all_boundaries = [b for bounds in per_row_boundaries for b in bounds]
    clusters = _cluster_1d(all_boundaries, boundary_tolerance_pt)
    if not clusters:
        return [], median_gap

    # Each row votes for the set of boundaries it exhibits. The winning
    # signature is the layout of the table; header rows, addresses and prose
    # paragraphs produce different signatures and are ignored by construction.
    signatures: Counter[tuple[int, ...]] = Counter()
    for bounds in per_row_boundaries:
        hits = tuple(
            cluster_index
            for cluster_index, center in enumerate(clusters)
            if any(abs(b - center) <= boundary_tolerance_pt for b in bounds)
        )
        if 1 <= len(hits) <= 12:
            signatures[hits] += 1
    if not signatures:
        return [], median_gap

    # Score favours layouts that are both repeated and wide: a 5-column layout
    # on 16 rows describes the table better than a 2-column layout on 18 rows.
    signature, votes = max(
        signatures.items(), key=lambda item: item[1] * (len(item[0]) + 1)
    )
    minimum_votes = max(3, int(round(min_row_support * len(rows))))
    if votes < minimum_votes:
        return [], median_gap

    boundaries = [clusters[index] for index in sorted(signature)]
    left_edge = min(w.bbox.x0 for r in rows for w in r.words) - 1.0
    right_edge = max(w.bbox.x1 for r in rows for w in r.words) + 1.0
    edges = [left_edge] + boundaries + [right_edge]
    columns = [Column(index=i, x0=edges[i], x1=edges[i + 1]) for i in range(len(edges) - 1)]
    return columns, median_gap


def _cluster_1d(values: list[float], tolerance: float) -> list[float]:
    """Greedy 1-D clustering of boundary positions into stable column edges."""
    if not values:
        return []
    ordered = sorted(values)
    clusters: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [statistics.fmean(cluster) for cluster in clusters]


def assign_segments(rows: list[Row], columns: list[Column]) -> list[int]:
    """Return the number of distinct columns each row occupies."""
    if not columns:
        return [1] * len(rows)
    edges = [c.x0 for c in columns] + [columns[-1].x1]
    counts: list[int] = []
    for row in rows:
        used = set()
        for word in row.words:
            center = (word.bbox.x0 + word.bbox.x1) / 2.0
            index = 0
            while index < len(edges) - 1 and center >= edges[index + 1]:
                index += 1
            used.add(index)
        counts.append(len(used))
    return counts


def find_table_bands(
    rows: list[Row],
    columns: list[Column],
    *,
    min_rows: int = 3,
    max_gap_rows: int = 2,
) -> list[tuple[int, int]]:
    """Locate contiguous y-bands of multi-column rows (candidate tables).

    A laboratory page mixes tables with prose, headings and method notes, so
    column inference must be restricted to the dense band or it will pick up
    spurious boundaries from full-width prose lines.

    Returns inclusive ``(start, end)`` index pairs into ``rows``.
    """
    counts = assign_segments(rows, columns)
    bands: list[tuple[int, int]] = []
    start: int | None = None
    last_multi: int | None = None
    for index, count in enumerate(counts):
        if count >= 3:
            if start is None:
                start = index
            last_multi = index
        elif start is not None and last_multi is not None and index - last_multi > max_gap_rows:
            if last_multi - start + 1 >= min_rows:
                bands.append((start, last_multi))
            start = None
            last_multi = None
    if start is not None and last_multi is not None and last_multi - start + 1 >= min_rows:
        bands.append((start, last_multi))
    return bands


def measure_table_structure(
    page: pymupdf.Page,
    *,
    min_gap_pt: float = 10.0,
) -> TableProbe:
    """Probe whether a page's text layer retains table geometry.

    Two passes: a coarse pass finds candidate table bands, then column inference
    is re-run on the largest band alone so that prose and header lines do not
    contribute spurious boundaries. Metrics are reported for that band, which is
    what the extraction layer will actually consume.
    """
    words = extract_words_exact(page)
    rows = cluster_rows(words)
    if not rows:
        return TableProbe(0, 0, 0, 0, 0.0, 0.0, False, ["no words on page"])

    threshold = gap_threshold(rows, min_gap_pt=min_gap_pt)
    coarse_columns, median_gap = infer_columns(
        rows, min_gap_pt=min_gap_pt, threshold=threshold
    )
    bands = find_table_bands(rows, coarse_columns) if coarse_columns else []
    if not bands:
        return TableProbe(
            row_count=len(rows),
            column_count=len(coarse_columns),
            table_row_count=0,
            modal_segment_count=0,
            segment_consistency=0.0,
            median_row_gap_pt=round(median_gap, 1),
            usable=False,
            notes=["no contiguous multi-column band found"],
        )

    start, end = max(bands, key=lambda b: b[1] - b[0])
    band_rows = rows[start : end + 1]
    columns, median_gap = infer_columns(
        band_rows,
        min_gap_pt=min_gap_pt,
        min_row_support=0.0,
        threshold=threshold,
        boundary_tolerance_pt=8.0,
    )
    counts = assign_segments(band_rows, columns)
    for row, count in zip(band_rows, counts):
        row.segments = count

    table_counts = [c for c in counts if c >= 3]
    table_row_count = len(table_counts)
    if table_counts:
        modal, modal_count = Counter(table_counts).most_common(1)[0]
        consistency = modal_count / table_row_count
    else:
        modal, consistency = 0, 0.0

    usable = table_row_count >= 3 and modal >= 3
    notes: list[str] = []
    if len(columns) < 3:
        notes.append(f"only {len(columns)} column band(s) detected")
    if consistency < 0.6:
        notes.append(
            f"row segmentation varies (modal {modal} bands, {consistency:.0%} of table rows); "
            "page probably holds several table blocks with different widths"
        )

    return TableProbe(
        row_count=len(rows),
        column_count=len(columns),
        table_row_count=table_row_count,
        modal_segment_count=modal,
        segment_consistency=round(consistency, 3),
        median_row_gap_pt=round(median_gap, 1),
        usable=usable,
        notes=notes,
    )
