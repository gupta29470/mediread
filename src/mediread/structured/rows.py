"""Table reconstruction over the ingestion contract.

Input: the ``lines`` of one ``mediread.extraction/1`` page (embedded text or OCR,
already normalised to page points with geometric reading order).

Output: table blocks with a **header-derived column map**, and per-row cells
assigned by geometry. Nothing here interprets laboratory values; it only decides
"which words belong to which column of which row".

Why header-driven rather than fixed columns: the corpus contains at least three
table shapes on the same producer —

* ``TEST NAME | TECHNOLOGY | VALUE | UNITS | Bio. Ref. Interval.``   (5 columns)
* ``TEST NAME | TECHNOLOGY | VALUE | UNITS``  with the range on a following row (4 columns)
* ``TEST NAME | VALUE | UNITS | Bio. Ref. Interval.``                 (4 columns, no method)
* ``TEST NAME | OBSERVATION | UNITS | Bio. Ref. Interval.``           (urine)

A fixed schema would mis-assign cells on at least two of them.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Iterable

from ..models import BBox, TextLine, TextWord
from . import vocabulary as vocab

# Header token -> semantic role.
_HEADER_ROLES: dict[str, str] = {
    "test": "test", "tests": "test", "name": "test", "investigation": "test",
    "parameter": "test", "analysis": "test", "particulars": "test",
    "technology": "method", "method": "method", "technique": "method",
    "value": "value", "values": "value", "result": "value", "results": "value",
    "observation": "value", "observations": "value", "finding": "value",
    "unit": "unit", "units": "unit",
    "bio": "range", "ref": "range", "reference": "range", "range": "range",
    "interval": "range", "normal": "range", "biological": "range",
    "ref.": "range", "bio.": "range", "interval.": "range", "range.": "range",
    "bio.ref": "range", "bio.ref.": "range", "ref.range": "range",
}

_ROLE_ORDER = ("test", "method", "value", "unit", "range")

_WS = re.compile(r"\s+")


def _clean_token(token: str) -> str:
    return token.strip().lower().strip(",;:")


@dataclass
class Column:
    role: str
    x0: float
    x1: float
    label: str

    def to_dict(self) -> dict:
        return {"role": self.role, "x0": round(self.x0, 1), "x1": round(self.x1, 1), "label": self.label}


@dataclass
class Cell:
    role: str
    text: str
    bbox: BBox | None
    words: list[TextWord] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.text.strip()


@dataclass
class TableRow:
    index: int
    y: float
    cells: dict[str, Cell]
    all_words: list[TextWord] = field(default_factory=list)

    @property
    def raw_text(self) -> str:
        return " ".join(w.text for w in self.all_words).strip()

    def cell(self, role: str) -> Cell:
        return self.cells.get(role) or Cell(role=role, text="", bbox=None)

    @property
    def bbox(self) -> BBox:
        if not self.all_words:
            return BBox(0, self.y, 0, self.y)
        return BBox(
            min(w.bbox.x0 for w in self.all_words),
            min(w.bbox.y0 for w in self.all_words),
            max(w.bbox.x1 for w in self.all_words),
            max(w.bbox.y1 for w in self.all_words),
        )


@dataclass
class TableBlock:
    page: int
    header_text: str
    columns: list[Column]
    rows: list[TableRow]
    y0: float
    y1: float

    @property
    def roles(self) -> list[str]:
        return [c.role for c in self.columns]


@dataclass
class PageTables:
    page: int
    width: float
    height: float
    rows: list[TableRow]
    blocks: list[TableBlock]
    headings: list[tuple[int, str]]      # (row index, text) of in-table headings
    has_header: bool


def words_from_lines(lines: Iterable[TextLine]) -> list[TextWord]:
    out: list[TextWord] = []
    for line in lines:
        if line.words:
            out.extend(line.words)
        else:  # defensive: keep the line as one word
            out.append(TextWord(text=line.text, bbox=line.bbox, confidence=line.confidence))
    return out


def cluster_rows(words: list[TextWord], y_factor: float = 0.6) -> list[list[TextWord]]:
    """Group words into visual rows by vertical centre (same rule as ingestion)."""
    if not words:
        return []
    heights = [w.bbox.height for w in words if w.bbox.height > 0]
    median_h = statistics.median(heights) if heights else 9.0
    tolerance = max(2.0, median_h * y_factor)
    ordered = sorted(words, key=lambda w: ((w.bbox.y0 + w.bbox.y1) / 2.0, w.bbox.x0))
    groups: list[list[TextWord]] = [[ordered[0]]]
    center = (ordered[0].bbox.y0 + ordered[0].bbox.y1) / 2.0
    for word in ordered[1:]:
        word_center = (word.bbox.y0 + word.bbox.y1) / 2.0
        if abs(word_center - center) <= tolerance:
            groups[-1].append(word)
            center = statistics.fmean((w.bbox.y0 + w.bbox.y1) / 2.0 for w in groups[-1])
        else:
            groups.append([word])
            center = word_center
    for group in groups:
        group.sort(key=lambda w: w.bbox.x0)
    return groups


# --------------------------------------------------------------------------
# Header detection
# --------------------------------------------------------------------------


def _header_roles(row: list[TextWord]) -> list[tuple[str, TextWord]]:
    roles: list[tuple[str, TextWord]] = []
    for word in row:
        token = _clean_token(word.text)
        role = _HEADER_ROLES.get(token)
        if role:
            roles.append((role, word))
    return roles


def is_header_row(row: list[TextWord]) -> bool:
    """A header must name at least a value column plus test/unit/range support."""
    roles = {role for role, _ in _header_roles(row)}
    if "value" not in roles:
        return False
    return len(roles & {"test", "unit", "range"}) >= 1


def build_columns(row: list[TextWord]) -> list[Column] | None:
    """Merge consecutive same-role header tokens into columns."""
    roles = _header_roles(row)
    if not roles:
        return None
    columns: list[Column] = []
    current_role, first_word = roles[0]
    current_words: list[TextWord] = [first_word]
    for role, word in roles[1:]:
        if role == current_role:
            current_words.append(word)
        else:
            columns.append(_make_column(current_role, current_words))
            current_role, current_words = role, [word]
    columns.append(_make_column(current_role, current_words))

    roles_present = {c.role for c in columns}
    if "value" not in roles_present:
        return None
    if "test" not in roles_present and "range" not in roles_present:
        return None
    return columns


def _make_column(role: str, words: list[TextWord]) -> Column:
    label = " ".join(w.text for w in words).strip()
    return Column(
        role=role,
        x0=min(w.bbox.x0 for w in words),
        x1=max(w.bbox.x1 for w in words),
        label=label,
    )


def _boundaries(columns: list[Column]) -> list[float]:
    """Cell boundaries are the midpoints between adjacent header columns."""
    ordered = sorted(columns, key=lambda c: c.x0)
    return [(a.x1 + b.x0) / 2.0 for a, b in zip(ordered, ordered[1:])]


def _row_groups(words: list[TextWord], gap_threshold: float) -> list[list[TextWord]]:
    """Split a row into cell groups at wide horizontal gaps."""
    if not words:
        return []
    ordered = sorted(words, key=lambda w: w.bbox.x0)
    groups: list[list[TextWord]] = [[ordered[0]]]
    for previous, current in zip(ordered, ordered[1:]):
        if current.bbox.x0 - previous.bbox.x1 >= gap_threshold:
            groups.append([current])
        else:
            groups[-1].append(current)
    return groups


def assign_cells(
    row_words: list[TextWord],
    columns: list[Column],
    *,
    gap_threshold: float = 12.0,
) -> dict[str, Cell]:
    """Assign cell groups to header columns by nearest header centre.

    Words are first grouped at wide gaps, then *each group as a whole* is mapped
    to the nearest header column. Per-word assignment fails when a header label
    is centred over its column while the data is left-aligned: on the blood
    grouping page the value ``B`` sits 2 pt outside the ``VALUE`` header span and
    was silently appended to the technology cell.
    """
    if not columns:
        return {}
    ordered = sorted(columns, key=lambda c: c.x0)
    centers = [((c.x0 + c.x1) / 2.0, index) for index, c in enumerate(ordered)]
    buckets: dict[str, list[TextWord]] = {c.role: [] for c in ordered}

    for group in _row_groups(row_words, gap_threshold):
        group_center = (
            min(w.bbox.x0 for w in group) + max(w.bbox.x1 for w in group)
        ) / 2.0
        _, index = min(centers, key=lambda item: abs(item[0] - group_center))
        buckets[ordered[index].role].extend(group)

    cells: dict[str, Cell] = {}
    for role, words in buckets.items():
        if not words:
            cells[role] = Cell(role=role, text="", bbox=None)
            continue
        words.sort(key=lambda w: w.bbox.x0)
        text = " ".join(w.text for w in words).strip()
        bbox = BBox(
            min(w.bbox.x0 for w in words),
            min(w.bbox.y0 for w in words),
            max(w.bbox.x1 for w in words),
            max(w.bbox.y1 for w in words),
        )
        cells[role] = Cell(role=role, text=text, bbox=bbox, words=words)
    return cells


def page_gap_threshold(rows: list[list[TextWord]]) -> float:
    """Adaptive cell-gap threshold from the page's own word spacing."""
    import statistics as _statistics

    gaps = [
        right.bbox.x0 - left.bbox.x1
        for row in rows
        for left, right in zip(row, row[1:])
        if right.bbox.x0 - left.bbox.x1 > 0
    ]
    if not gaps:
        return 12.0
    lower_quartile = sorted(gaps)[len(gaps) // 4]
    # Clamp: on a sparse page (few rows) the quartile can be a cell gap itself,
    # which would merge every column; on a dense page it stays at the word gap.
    return min(25.0, max(10.0, 3.0 * lower_quartile))


# --------------------------------------------------------------------------
# Page-level reconstruction
# --------------------------------------------------------------------------


def build_page_tables(
    page_number: int,
    lines: list[TextLine],
    width: float,
    height: float,
) -> PageTables:
    """Reconstruct rows, identify header blocks and assign cells per block."""
    words = words_from_lines(lines)
    grouped = cluster_rows(words)
    all_rows: list[TableRow] = []
    for index, group in enumerate(grouped):
        y = statistics.fmean((w.bbox.y0 + w.bbox.y1) / 2.0 for w in group)
        text = " ".join(w.text for w in group)
        all_rows.append(
            TableRow(index=index, y=y, cells={"raw": Cell("raw", text, None, group)}, all_words=group)
        )

    blocks: list[TableBlock] = []
    headings: list[tuple[int, str]] = []
    header_indices = [row.index for row in all_rows if is_header_row(row.all_words)]
    gap_threshold = page_gap_threshold([r.all_words for r in all_rows])

    for header_index in header_indices:
        columns = build_columns(all_rows[header_index].all_words)
        if not columns:
            continue
        start = header_index
        end = len(all_rows)
        for next_header in header_indices:
            if next_header > header_index:
                end = next_header
                break
        rows: list[TableRow] = []
        for row in all_rows[start + 1 : end]:
            if not row.all_words:
                continue
            # A block ends at report furniture that cannot belong to a table.
            first = row.all_words[0].text.lower()
            if re.match(
                r"^(sample|barcode|labcode|report|page|note|end of report|"
                r"clinically tested|conditions of reporting|v\b)",
                first,
            ):
                break
            cells = assign_cells(row.all_words, columns, gap_threshold=gap_threshold)
            rows.append(TableRow(index=row.index, y=row.y, cells=cells, all_words=row.all_words))
        if rows:
            blocks.append(
                TableBlock(
                    page=page_number,
                    header_text=" ".join(w.text for w in all_rows[header_index].all_words),
                    columns=columns,
                    rows=rows,
                    y0=all_rows[start].y,
                    y1=rows[-1].y,
                )
            )

    # In-table headings: single-cell rows of pure text inside a block.
    for block in blocks:
        for row in block.rows:
            tokens = [w.text for w in row.all_words]
            if len(tokens) <= 4 and all(re.search(r"[A-Za-z]", t) for t in tokens):
                text = " ".join(tokens)
                if _looks_like_heading(text):
                    headings.append((row.index, text))

    return PageTables(
        page=page_number,
        width=width,
        height=height,
        rows=all_rows,
        blocks=blocks,
        headings=headings,
        has_header=bool(header_indices),
    )


_HEADING_STOPWORDS = {
    "test", "name", "value", "units", "result", "reference", "range", "interval",
    "technology", "method", "observation",
}


def _looks_like_heading(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered or len(lowered) > 48:
        return False
    if any(stop in lowered for stop in _HEADING_STOPWORDS):
        return False
    if re.search(r"\d", lowered):
        return False
    return any(
        keyword in lowered
        for keyword in (
            "examination", "complete", "differential", "count", "profile",
            "urinogram", "microscopic", "physical", "chemical", "absolute",
            "ratio", "index", "study", "panel",
        )
    )


def heading_for_row(tables: PageTables, row_index: int) -> str | None:
    """Most recent heading at or above ``row_index`` within the page."""
    best = None
    for index, text in sorted(tables.headings):
        if index <= row_index:
            best = text
        else:
            break
    return best


def section_from_header_text(text: str) -> vocab.Section | None:
    lowered = text.lower()
    for section, keywords in vocab.SECTION_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lowered:
                return section
    return None
