"""Row state machine: table rows -> candidate laboratory results.

The hard part is not parsing a cell, it is deciding *which cells belong
together*. This corpus shows all of the following, sometimes on one page:

* every field in one row (hemogram),
* the reference range on the row after a ``Bio. Ref. Interval. :`` label (PT/INR,
  electrolytes, phosphorus),
* a stratified reference table spanning five rows (eGFR, HbA1c),
* the test name on its own row with the value row beneath it (HbA1c),
* section headings interleaved with result rows (urine analysis),
* prose and method notes between results (liver, kidney),
* qualitative results with ``-`` as the unit placeholder (urine).

The machine tracks three things: the current section heading, an orphan test
name that may belong to the next row, and a result awaiting its reference range.
Everything it rejects is recorded as an :class:`UnparsedRow` with a reason.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..models import BBox
from . import vocabulary as vocab
from .rows import PageTables, TableBlock, TableRow, heading_for_row
from .schema import (
    Evidence,
    Field,
    FieldStatus,
    LabResult,
    UnparsedRow,
    ValueKind,
    ReferenceRange,
    worst_status,
)
from .text import (
    is_reference_label,
    looks_numeric,
    looks_qualitative,
    parse_number,
    parse_reference,
)

_WS = re.compile(r"\s+")
_FOOTNOTE = re.compile(r"^([0-9.,]+)\s*[*†‡#]+$")
_BOUND_VALUE = re.compile(r"^\s*(?P<op>[<>]=?)\s*(?P<value>\d+(?:\.\d+)?)\s*$")
_VALUE_RANGE = re.compile(
    r"^\s*(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?P<high>\d+(?:\.\d+)?)\s*$"
)

_REFERENCE_DESCRIPTOR = re.compile(
    r"^(?:normal|good control|fair control|poor control|unsatisfactory control|"
    r"prediabetic|diabetic|mild(?: to moderate)?(?: decrease)?|moderate(?: to severe)?"
    r"(?: decrease)?|severe(?: decrease)?|decrease|normal range|high|low)$",
    re.IGNORECASE,
)

_NESTED_DESCRIPTOR = re.compile(
    r"^(?:desirable|borderline|high|low|normal|optimal|risk|acceptable|"
    r"total cholesterol\s*\()", re.IGNORECASE
)

_FURNITURE = re.compile(
    r"^(?:method|clinical significance|note|please correlate|sample|barcode|labcode|"
    r"report|page|end of report|~~|clinically tested|conditions of reporting|"
    r"test asked|ref\.? by|name\b|address|doctor|dr\.|remarks|alert|"
    r"interpretation|impression|advised|disclaimer|specifications|references)",
    re.IGNORECASE,
)

_BAND_PREFIX = re.compile(
    r"^\s*(?:"
    r"[<>]\s*=?\s*\d"                       # "> = 90", "<5.7%"
    r"|below\s*\d|above\s*\d|up\s*to\s*\d"
    r"|\d+(?:\.\d+)?\s*%?\s*[-–—]\s*\d"     # "45 - 59", "5.7% - 6.4%"
    r"|\d+\s*:\s*\d"                         # "9:1-23:1"
    r"|adults?\b|males?\b|females?\b|children\b|trimester\b"
    r"|\d(?:st|nd|rd|th)\s"
    r")",
    re.IGNORECASE,
)

_RANGE_ROW_HINT = re.compile(
    r"^\s*(?:adults?|males?|females?|children|child|newborn|infant|age|"
    r"[<>]=?\s*\d|below|above|up to|less than|greater than|more than|normal|"
    r"negative|positive|absent|present|nil|not detected|trace|clear|pale|yellow|"
    r"amber|straw|cloudy)\b",
    re.IGNORECASE,
)


_FUNCTION_WORDS = {
    "the", "and", "of", "is", "are", "for", "with", "that", "this", "has",
    "have", "can", "may", "should", "which", "when", "from", "by", "to", "in",
    "on", "at", "as", "an", "a", "be", "been", "was", "were", "or", "not",
    "has", "its", "it", "their", "these", "those", "than", "then", "also",
}


def _is_prose(text: str) -> bool:
    """Sentence-like text, detected by function words — not by lowercase units.

    Counting lowercase tokens classified "EST. GLOMERULAR FILTRATION RATE (eGFR)
    CALCULATED 112 mL/min/1.73 m2" as prose because ``mL/min/1.73`` and ``m2``
    are lowercase. Function words ("of", "the", "with") are the reliable signal.
    """
    words = re.findall(r"[A-Za-z]+", text.lower())
    if len(words) < 5:
        return False
    return sum(1 for w in words if w in _FUNCTION_WORDS) >= 2


def _looks_like_range(text: str) -> bool:
    if not text.strip():
        return False
    cleaned = re.sub(r">\s*=", ">=", re.sub(r"<\s*=", "<=", text))
    if re.search(r"\d\s*(?:-|–|—|to)\s*\d", cleaned):
        return True
    if re.search(r"[<>]\s*=?\s*\d", cleaned):
        return True
    return bool(_RANGE_ROW_HINT.match(cleaned))


def _strip_reference_label(text: str) -> str:
    """Return text following a reference-range label, if any."""
    match = re.match(
        r"^\s*bio\.?\s*ref\.?\s*interval\.?\s*:?\s*-?\s*(?P<rest>.*)$",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group("rest").strip(" :-|")
    match = re.match(
        r"^\s*reference\s*(?:range|interval)\s*:?\s*(?P<rest>.*)$", text, re.IGNORECASE
    )
    return match.group("rest").strip(" :-|") if match else ""


_TRAILING_RANGE = re.compile(
    r"^(?P<unit>.+?)\s+(?P<range>(?:[<>]\s*=?\s*)?\d+(?:\.\d+)?\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?)$"
)


_DASH_GROUPS = re.compile(r"^(?P<unit>[-–—])\s+(?P<range>[-–—]{2,})$")


_TRAILING_MARKER = re.compile(r"^(?P<value>.*[A-Za-z])\s+(?P<marker>(?:-{1,3}|N/A|n/a))$")


def _split_trailing_marker(value_text: str, unit_text: str) -> tuple[str, str]:
    """Move a trailing no-unit marker out of a qualitative value cell.

    "CRYSTALS | CALCIUM OXALATE CRYSTALS -" happens when the dash sits close to
    the text: the dash is the unit cell's marker, not part of the result.
    """
    if unit_text.strip():
        return value_text, unit_text
    match = _TRAILING_MARKER.match(value_text.strip())
    if not match:
        return value_text, unit_text
    return match.group("value").strip(), match.group("marker")


def _split_unit_range(unit_text: str, range_text: str) -> tuple[str, str, bool]:
    """Split a unit cell that swallowed the range ("cells/HPF 0-5", "- --")."""
    if range_text.strip() or not unit_text.strip():
        return unit_text, range_text, False
    dash_match = _DASH_GROUPS.match(unit_text.strip())
    if dash_match:
        return dash_match.group("unit"), dash_match.group("range"), True
    match = _TRAILING_RANGE.match(unit_text.strip())
    if not match:
        return unit_text, range_text, False
    unit_part = match.group("unit").strip()
    if vocab.match_unit(unit_part).status not in (
        vocab.UnitStatus.EXACT,
        vocab.UnitStatus.VARIANT,
        vocab.UnitStatus.AMBIGUOUS,
    ):
        return unit_text, range_text, False
    return unit_part, match.group("range").strip(), True


def _strip_footnote(text: str) -> tuple[str, bool]:
    match = _FOOTNOTE.match(text.strip())
    if match:
        return match.group(1), True
    return text.strip(), False


def _make_evidence(cell_words, page: int, fallback_bbox: BBox | None = None) -> Evidence | None:
    words = list(cell_words or [])
    if words:
        bbox = BBox(
            min(w.bbox.x0 for w in words),
            min(w.bbox.y0 for w in words),
            max(w.bbox.x1 for w in words),
            max(w.bbox.y1 for w in words),
        )
        confidence = (
            sum(w.confidence for w in words if w.confidence is not None) / len(words)
            if any(w.confidence is not None for w in words)
            else None
        )
        return Evidence(
            page=page,
            bbox=bbox.to_list(),
            text=" ".join(w.text for w in words),
            origin="ocr" if words[0].confidence is not None else "embedded",
            confidence=confidence,
        )
    if fallback_bbox is not None:
        return Evidence(page=page, bbox=fallback_bbox.to_list(), text="")
    return None


@dataclass
class Candidate:
    """A row (or row group) that looks like a laboratory result."""

    block: TableBlock
    row: TableRow
    test_text: str
    method_text: str
    value_text: str
    unit_text: str
    range_text: str
    heading: str | None
    test_words: list = field(default_factory=list)
    value_words: list = field(default_factory=list)
    unit_words: list = field(default_factory=list)
    range_words: list = field(default_factory=list)
    range_from_continuation: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class Rejected:
    page: int
    text: str
    bbox: list[float]
    reason: str


def collect_candidates(tables: PageTables) -> tuple[list[Candidate], list[Rejected]]:
    """Walk every table block and produce candidates plus rejected rows."""
    candidates: list[Candidate] = []
    rejected: list[Rejected] = []

    for block in tables.blocks:
        pending_test: tuple[str, int, list] | None = None   # (text, row index, words)
        awaiting_range_for: int | None = None               # index into candidates
        skip_until_row = -1

        for row in block.rows:
            text = row.raw_text
            if not text:
                continue
            if row.index <= skip_until_row:
                continue

            heading = heading_for_row(tables, row.index)
            test_cell = row.cell("test")
            value_cell = row.cell("value")
            unit_cell = row.cell("unit")
            range_cell = row.cell("range")

            # 1. Reference label ("Bio. Ref. Interval. :") arms range capture.
            #    Checked before prose detection: the label row is often followed
            #    by explanatory text that would otherwise be classified as prose
            #    and disarm the capture.
            if is_reference_label(test_cell.text) or is_reference_label(text):
                if candidates:
                    awaiting_range_for = len(candidates) - 1
                    extra = _strip_reference_label(text)
                    if extra:
                        candidate = candidates[awaiting_range_for]
                        candidate.range_text = (
                            f"{candidate.range_text} | {extra}" if candidate.range_text else extra
                        )
                        candidate.range_from_continuation = True
                continue

            # 2. Furniture / prose / known non-result labels.
            if _FURNITURE.match(text) or _is_prose(text):
                if awaiting_range_for is not None and _looks_like_range(text) is False:
                    awaiting_range_for = None
                pending_test = None
                continue

            # 3. A pure range row while a result is awaiting its range.
            #    Band tables (eGFR, HbA1c) frequently centre the band text so it
            #    lands in the value column; the prefix is the reliable signal.
            band_like = bool(_BAND_PREFIX.match(text))
            pure_range = not value_cell.text.strip() and _looks_like_range(test_cell.text or text)
            if awaiting_range_for is not None and (pure_range or band_like):
                candidate = candidates[awaiting_range_for]
                continuation_text = (test_cell.text or text).strip()
                if candidate.range_text:
                    candidate.range_text += " | " + continuation_text
                else:
                    candidate.range_text = continuation_text
                candidate.range_from_continuation = True
                candidate.range_words.extend(test_cell.words or [])
                if not (band_like or _looks_like_range(continuation_text)) or re.match(
                    r"^\s*(?:method|clinical|note|please)", continuation_text, re.IGNORECASE
                ):
                    awaiting_range_for = None
                continue
            awaiting_range_for = None

            # 4. Row with a test name but no value: heading, orphan name, or note.
            if test_cell.text.strip() and not value_cell.text.strip():
                heading_text = test_cell.text.strip()
                if heading_text in {h for _, h in tables.headings}:
                    pending_test = None
                    continue
                if len(heading_text.split()) <= 4 and re.search(r"[A-Za-z]", heading_text):
                    pending_test = (heading_text, row.index, test_cell.words)
                    continue
                rejected.append(
                    Rejected(tables.page, text, row.bbox.to_list(), "row has test text but no value")
                )
                pending_test = None
                continue

            # 5. Row with a value.
            if value_cell.text.strip() or range_cell.text.strip():
                # Nested risk-band headers ("DESIRABLE <200", "BORDERLINE HIGH
                # 200-239") and inline column headers ("TOTAL CHOLESTEROL
                # (mg/dl)") are layout, not results.
                if _NESTED_DESCRIPTOR.match(test_cell.text.strip()):
                    rejected.append(
                        Rejected(tables.page, text, row.bbox.to_list(),
                                 "nested risk-band header, not a result row")
                    )
                    continue
                value_stripped = value_cell.text.strip()
                looks_like_column_header = (
                    re.fullmatch(r"\(\s*[A-Za-z%µ/0-9.^]+\s*\)", value_stripped) is not None
                )
                if looks_like_column_header:
                    rejected.append(
                        Rejected(tables.page, text, row.bbox.to_list(),
                                 "nested column header, not a result row")
                    )
                    continue
                if _REFERENCE_DESCRIPTOR.match(value_cell.text.strip()) and (
                    not test_cell.text.strip()
                    or not re.match(r"^[A-Za-z]", test_cell.text.strip())
                ):
                    rejected.append(
                        Rejected(tables.page, text, row.bbox.to_list(),
                                 "value cell holds a reference descriptor, not a result")
                    )
                    continue
                test_text = test_cell.text.strip()
                test_words = list(test_cell.words)
                if not test_text and pending_test and row.index - pending_test[1] <= 2:
                    test_text, _, test_words = pending_test
                    pending_test = None
                if not test_text:
                    rejected.append(
                        Rejected(tables.page, text, row.bbox.to_list(),
                                 "value row without an identified test name")
                    )
                    continue
                candidate = Candidate(
                    block=block,
                    row=row,
                    test_text=test_text,
                    method_text=row.cell("method").text.strip(),
                    value_text=value_cell.text.strip(),
                    unit_text=unit_cell.text.strip(),
                    range_text=range_cell.text.strip(),
                    heading=heading,
                    test_words=test_words,
                    value_words=list(value_cell.words),
                    unit_words=list(unit_cell.words),
                    range_words=list(range_cell.words),
                )
                candidates.append(candidate)
                pending_test = None
                continue

            # 6. Anything else inside a table.
            rejected.append(
                Rejected(tables.page, text, row.bbox.to_list(), "row matched no result pattern")
            )
            pending_test = None

    return candidates, rejected


# --------------------------------------------------------------------------
# Headerless pages
# --------------------------------------------------------------------------

# Page-level metadata means the page is a cover/summary, not a result table.
_HEADERLESS_METADATA = re.compile(
    r"^(?:report for|test date|report status|tests asked|report availability)",
    re.IGNORECASE,
)
# Rows that are ordinary surrounding text on a result page.
_HEADERLESS_SKIP = re.compile(
    r"^(?:sample|barcode|labcode|collected|released|received|reference range|comments|"
    r"method|interpretation|clinical|note|please|technology|page|dr\.|labcode)",
    re.IGNORECASE,
)


def headerless_candidates(tables: PageTables) -> tuple[list[Candidate], list[Rejected]]:
    """Extract results from a page that has no table header.

    Only used when header detection finds nothing (e.g. the single-page
    haemoglobin electrophoresis report). The rule is deliberately narrow: a row
    qualifies only when it is ``<test label> <number>`` with nothing else, so
    cover pages, summary pages and reference-range lines cannot fabricate
    results. Fields are then marked uncertain downstream because the column
    roles were inferred, not declared.
    """
    candidates: list[Candidate] = []
    rejected: list[Rejected] = []
    rows = tables.rows
    if any(_HEADERLESS_METADATA.match(r.raw_text) for r in rows):
        # Cover/summary pages: not a result table.
        return [], [
            Rejected(tables.page, r.raw_text, r.bbox.to_list(),
                     "page has no table header and contains report metadata")
            for r in rows[:3]
        ]

    for row in rows:
        words = row.all_words
        if _HEADERLESS_SKIP.match(row.raw_text):
            continue
        if len(words) < 2 or len(words) > 9:
            continue
        numeric_index = next((i for i, w in enumerate(words) if looks_numeric(w.text)), None)
        if numeric_index is None or numeric_index == 0:
            continue
        test_text = " ".join(w.text for w in words[:numeric_index]).strip()
        value_text = words[numeric_index].text
        trailing = " ".join(w.text for w in words[numeric_index + 1 :]).strip()
        if not re.search(r"[A-Za-z]{2,}", test_text):
            continue
        if trailing and trailing not in {"<", ">"}:
            continue
        if _FURNITURE.match(test_text) or _is_prose(test_text):
            continue
        candidate = Candidate(
            block=TableBlock(
                page=tables.page, header_text="(none — geometry inferred)",
                columns=[], rows=[row], y0=row.y, y1=row.y,
            ),
            row=row,
            test_text=test_text,
            method_text="",
            value_text=value_text,
            unit_text="",
            range_text="",
            heading=None,
            test_words=words[:numeric_index],
            value_words=[words[numeric_index]],
            notes=["row parsed without a table header; column roles inferred from geometry"],
        )
        if trailing:
            candidate.notes.append(f"trailing comparison marker '{trailing}' not used as a bound")
        candidates.append(candidate)
    return candidates, rejected


# --------------------------------------------------------------------------
# Candidate -> LabResult
# --------------------------------------------------------------------------


def _split_value_unit(value_text: str, unit_text: str) -> tuple[str, str, bool]:
    """Split a value cell that swallowed its unit.

    Happens when OCR shifts a column boundary: the value cell becomes
    ``"6.02 X 10³ / µL"``. The numeric head is the value, the rest is a unit
    candidate recovered from the same cell (flagged, never silently trusted).
    """
    tokens = value_text.split()
    if len(tokens) <= 1 or unit_text.strip():
        return value_text, unit_text, False
    head, tail = tokens[0], " ".join(tokens[1:])
    if looks_numeric(head) and vocab.match_unit(tail).status in (
        vocab.UnitStatus.EXACT,
        vocab.UnitStatus.VARIANT,
        vocab.UnitStatus.AMBIGUOUS,
    ):
        return head, tail, True
    return value_text, unit_text, False


def build_result(
    candidate: Candidate,
    page: int,
    report_id: str,
    section: str,
    *,
    duplicate_signatures: set[tuple[str, str]] | None = None,
) -> LabResult:
    """Assemble one result with independently assessed fields."""
    value_text, unit_text, unit_recovered = _split_value_unit(
        candidate.value_text, candidate.unit_text
    )
    value_text, unit_text = _split_trailing_marker(value_text, unit_text)
    unit_text, split_range, range_recovered = _split_unit_range(unit_text, candidate.range_text)
    if range_recovered:
        candidate.notes.append("reference range recovered from the unit cell")
    value_core, footnote = _strip_footnote(value_text)

    number = parse_number(value_core)
    bound = _BOUND_VALUE.match(value_core) if not number.is_number else None
    test_hint = vocab.match_test(candidate.test_text)
    qualitative_label = None
    value_kind = ValueKind.NUMERIC if number.is_number else ValueKind.ABSENT

    if number.is_number:
        value_kind = ValueKind.NUMERIC
    elif bound:
        value_kind = ValueKind.NUMERIC
    elif _VALUE_RANGE.match(value_core):
        value_kind = ValueKind.TEXT
    elif looks_qualitative(value_core):
        qualitative_label = vocab.match_qualitative(value_core)
        value_kind = ValueKind.QUALITATIVE
    elif value_core.strip():
        value_kind = ValueKind.TEXT

    value_field = _build_value_field(
        raw=value_text,
        core=value_core,
        number=number,
        bound=bound,
        test_hint=test_hint,
        qualitative_label=qualitative_label,
        footnote=footnote,
        words=candidate.value_words,
        page=page,
        row_bbox=candidate.row.bbox,
    )

    qualitative_field = None
    if value_kind is ValueKind.QUALITATIVE:
        qualitative_field = _build_qualitative_field(
            value_text, qualitative_label, candidate.value_words, page, candidate.row.bbox
        )

    unit_field = _build_unit_field(
        unit_text, candidate.unit_words, page, unit_recovered, candidate.row.bbox
    )

    reference = parse_reference(split_range if range_recovered else candidate.range_text)
    reference_field = _build_reference_field(
        reference, candidate.range_words, page, candidate.row.bbox,
        from_continuation=candidate.range_from_continuation,
    )

    test_field = _build_test_field(
        candidate.test_text, candidate.test_words, page, candidate.row.bbox
    )

    warnings = list(candidate.notes)
    if unit_recovered:
        warnings.append("unit recovered from the value column (column boundary shifted)")
    if footnote:
        warnings.append("footnote marker removed from the numeric token for parsing only")

    result_id = _result_id(report_id, page, candidate.test_text, candidate.row.y)
    result = LabResult(
        result_id=result_id,
        report_id=report_id,
        page=page,
        section=section,
        test=test_field,
        value=value_field,
        unit=unit_field,
        reference=reference_field,
        qualitative=qualitative_field,
        method=candidate.method_text or None,
        value_kind=value_kind,
        row_bbox=candidate.row.bbox.to_list(),
        evidence_lines=[
            {
                "text": candidate.row.raw_text,
                "bbox": candidate.row.bbox.to_list(),
                "origin": "ocr"
                if candidate.row.all_words and candidate.row.all_words[0].confidence is not None
                else "embedded",
            }
        ],
        warnings=warnings,
    )
    from .validate import aggregate_status

    aggregate_status(result)
    return result


def _result_id(report_id: str, page: int, test: str, y: float) -> str:
    digest = hashlib.sha256(f"{report_id}|{page}|{test}|{y:.1f}".encode()).hexdigest()
    return digest[:12]


def _build_test_field(text: str, words, page: int, row_bbox: BBox) -> Field:
    raw = _WS.sub(" ", text).strip()
    evidence = _make_evidence(words, page, row_bbox)
    if not raw:
        return Field(status=FieldStatus.MISSING, reasons=["no test name in row"], evidence=evidence)

    if not re.search(r"[A-Za-z]", raw):
        return Field(raw=raw, status=FieldStatus.INVALID, confidence=0.2,
                     reasons=["test cell contains no letters"], evidence=evidence)

    match = vocab.match_test(raw)
    if match.exact and match.entry:
        return Field(
            raw=raw,
            status=FieldStatus.VERIFIED,
            confidence=0.99,
            normalized=match.test_id,
            reasons=[f"matched vocabulary: {match.entry.display}"],
            evidence=evidence,
        )
    if match.suggestion and match.suggestion_score >= 0.86:
        return Field(
            raw=raw,
            status=FieldStatus.UNCERTAIN,
            confidence=0.6,
            normalized=None,
            alternatives=[match.suggestion],
            reasons=[
                "no exact vocabulary match; closest known test is "
                f"'{match.suggestion}' ({match.suggestion_score:.0%} similar) — not merged"
            ],
            evidence=evidence,
        )
    return Field(
        raw=raw,
        status=FieldStatus.VERIFIED,
        confidence=0.8,
        normalized=None,
        reasons=["test name recognised in the test column; not in vocabulary"],
        evidence=evidence,
    )


def _build_value_field(
    *,
    raw: str,
    core: str,
    number,
    bound,
    test_hint,
    qualitative_label: str | None,
    footnote: bool,
    words,
    page: int,
    row_bbox: BBox,
) -> Field:
    evidence = _make_evidence(words, page, row_bbox)
    if not core.strip():
        return Field(status=FieldStatus.MISSING, reasons=["value cell is empty"], evidence=evidence)

    ocr_confidence = _cell_confidence(words)
    low_confidence = ocr_confidence is not None and ocr_confidence < 0.90

    if number.is_number:
        reasons = ["exact numeric token parsed"]
        status = FieldStatus.VERIFIED
        confidence = 1.0 if ocr_confidence is None else min(1.0, ocr_confidence)
        if low_confidence:
            status = FieldStatus.UNCERTAIN
            reasons.append(f"OCR confidence {ocr_confidence:.2f} below 0.90")
        if footnote:
            status = FieldStatus.REQUIRES_REVIEW if status is FieldStatus.VERIFIED else status
            reasons.append("footnote marker adjacent to the value")
        return Field(
            raw=raw,
            status=status,
            confidence=confidence,
            normalized=str(number.value),
            parsed={
                "value": str(number.value),
                "precision": number.precision,
                "has_thousands_separator": number.had_thousands_separator,
            },
            reasons=reasons,
            evidence=evidence,
        )

    if bound:
        return Field(
            raw=raw,
            status=FieldStatus.REQUIRES_REVIEW,
            confidence=0.6,
            normalized=f"{bound.group('op')}{bound.group('value')}",
            parsed={
                "value": bound.group("value"),
                "bound_operator": bound.group("op"),
                "precision": len(bound.group("value").split(".")[1]) if "." in bound.group("value") else 0,
            },
            reasons=["value is reported as a bound, not a measurement"],
            evidence=evidence,
        )

    range_match = _VALUE_RANGE.match(core)
    if range_match:
        return Field(
            raw=raw,
            status=FieldStatus.REQUIRES_REVIEW,
            confidence=0.5,
            normalized=range_match.group(0).strip(),
            parsed={
                "range_low": range_match.group("low"),
                "range_high": range_match.group("high"),
            },
            reasons=["result reported as a range (e.g. 1-2 per field), not a single value"],
            evidence=evidence,
        )

    if test_hint and test_hint.exact and test_hint.test_id in vocab.QUALITATIVE_BY_TEST:
        domain = vocab.QUALITATIVE_BY_TEST[test_hint.test_id]
        if core.strip().upper() in domain:
            return Field(
                raw=raw,
                status=FieldStatus.UNCERTAIN if low_confidence else FieldStatus.VERIFIED,
                confidence=0.9 if not low_confidence else 0.6,
                normalized=core.strip().upper(),
                parsed={"qualitative": core.strip().upper()},
                reasons=[f"test-specific qualitative value for {test_hint.test_id}"],
                evidence=evidence,
            )

    if qualitative_label:
        status = FieldStatus.UNCERTAIN if low_confidence else FieldStatus.VERIFIED
        return Field(
            raw=raw,
            status=status,
            confidence=0.9 if not low_confidence else 0.6,
            normalized=qualitative_label,
            parsed={"qualitative": qualitative_label},
            reasons=["qualitative result recognised"],
            evidence=evidence,
        )

    if looks_qualitative(core):
        return Field(
            raw=raw,
            status=FieldStatus.UNCERTAIN,
            confidence=0.45,
            reasons=["text result not in the qualitative vocabulary; requires review"],
            evidence=evidence,
        )

    return Field(
        raw=raw,
        status=FieldStatus.INVALID,
        confidence=0.1,
        reasons=[f"value cell is neither a number nor a qualitative result: {number.reason}"],
        evidence=evidence,
    )


def _cell_confidence(words) -> float | None:
    values = [w.confidence for w in words if w.confidence is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _build_qualitative_field(text, label, words, page: int, row_bbox: BBox) -> Field:
    evidence = _make_evidence(words, page, row_bbox)
    if label:
        return Field(
            raw=text,
            status=FieldStatus.VERIFIED,
            confidence=0.95,
            normalized=label,
            parsed={"qualitative": label},
            reasons=["recognised qualitative result"],
            evidence=evidence,
        )
    return Field(
        raw=text,
        status=FieldStatus.UNCERTAIN,
        confidence=0.4,
        reasons=["unrecognised qualitative text"],
        evidence=evidence,
    )


def _build_unit_field(
    text: str, words, page: int, recovered: bool, row_bbox: BBox
) -> Field:
    evidence = _make_evidence(words, page, row_bbox)
    raw = text.strip()
    if not raw:
        return Field(status=FieldStatus.MISSING, reasons=["unit cell is empty"], evidence=evidence)

    match = vocab.match_unit(raw)
    reasons: list[str] = []
    status = FieldStatus.UNCERTAIN
    confidence = 0.4
    alternatives = list(match.alternatives or [])

    if match.status is vocab.UnitStatus.EXACT:
        status, confidence = FieldStatus.VERIFIED, 0.99
        reasons.append("exact unit match")
    elif match.status is vocab.UnitStatus.VARIANT:
        status, confidence = FieldStatus.VERIFIED, 0.95
        reasons.append("known unit variant normalised")
    elif match.status is vocab.UnitStatus.NONE:
        status, confidence = FieldStatus.MISSING, 0.9
        reasons.append("report shows a no-unit marker for this test")
    elif match.status is vocab.UnitStatus.AMBIGUOUS:
        status, confidence = FieldStatus.REQUIRES_REVIEW, 0.3
        reasons.append(match.reason)
    else:
        status, confidence = FieldStatus.UNCERTAIN, 0.3
        reasons.append(match.reason)

    if recovered:
        status = FieldStatus.REQUIRES_REVIEW if status is FieldStatus.VERIFIED else status
        confidence = min(confidence, 0.5)
        reasons.append("unit was recovered from the value column")

    return Field(
        raw=raw,
        status=status,
        confidence=confidence,
        normalized=match.canonical,
        alternatives=alternatives,
        reasons=reasons,
        evidence=evidence,
    )


def _build_reference_field(
    reference: ReferenceRange,
    words,
    page: int,
    row_bbox: BBox,
    *,
    from_continuation: bool,
) -> Field:
    evidence = _make_evidence(words, page, row_bbox)
    if not reference.text:
        return Field(status=FieldStatus.MISSING, reasons=["no reference range reported"],
                     evidence=evidence)
    if reference.text.strip() in {"-", "--", "---", "n/a", "N/A", "Nil", "nil"}:
        return Field(
            raw=reference.text,
            status=FieldStatus.MISSING,
            confidence=0.8,
            reasons=["report shows a no-reference marker for this test"],
            evidence=evidence,
        )

    parsed = reference.to_dict()
    reasons: list[str] = []

    if reference.stratified:
        status, confidence = FieldStatus.REQUIRES_REVIEW, 0.3
        reasons.append("stratified or multi-band reference; bounds not parsed")
    elif reference.low is not None or reference.high is not None:
        status, confidence = FieldStatus.VERIFIED, 1.0
        reasons.append("numeric bounds parsed unambiguously")
        if reference.operator:
            reasons.append(f"one-sided bound ({reference.operator})")
    elif reference.qualitative:
        status, confidence = FieldStatus.VERIFIED, 0.9
        reasons.append("qualitative reference text")
    else:
        status, confidence = FieldStatus.REQUIRES_REVIEW, 0.3
        reasons.append("reference text could not be parsed into bounds")

    if from_continuation:
        confidence = min(confidence, 0.95)
        reasons.append("range taken from a continuation line below the result row")

    return Field(
        raw=reference.text,
        status=status,
        confidence=confidence,
        parsed=parsed,
        reasons=reasons,
        evidence=evidence,
        normalized=_format_range(reference),
    )


def _format_range(reference: ReferenceRange) -> str | None:
    """Compact, precision-preserving form of the interval ("12.0-15.0")."""
    if reference.stratified:
        return None
    if reference.low is not None and reference.high is not None:
        low = reference.low_text if reference.low_text is not None else f"{reference.low:g}"
        high = reference.high_text if reference.high_text is not None else f"{reference.high:g}"
        return f"{low}-{high}"
    if reference.operator and (reference.low is not None or reference.high is not None):
        bound = reference.low_text if reference.low is not None else reference.high_text
        if bound is None:
            value = reference.low if reference.low is not None else reference.high
            bound = f"{value:g}"
        return f"{reference.operator}{bound}"
    return None
