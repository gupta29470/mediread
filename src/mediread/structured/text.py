"""Value and reference-range parsing.

Everything here is deterministic and lossless: the raw string is always kept,
and parsing either succeeds unambiguously or reports why it failed. Numbers are
parsed with :class:`decimal.Decimal` so precision is never lost to binary
floating point, and a parsed number is never written back over the raw text.

The distinction between "a number" and "something that contains digits" is the
guard against dates, page numbers, barcodes and accession numbers entering a
measured-value field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .schema import ReferenceRange

# A measured value: optional sign, digits with optional single decimal point or
# thousands separators, optional exponent. Deliberately anchored so that
# "12/03/2024", "Page 5 of 10" and "BV621560" never match.
_NUMBER = re.compile(
    r"^(?P<sign>[+-])?"
    r"(?P<int>(?:\d{1,3}(?:,\d{2,3})+|\d+))"
    r"(?P<frac>\.\d+)?"
    r"(?P<exp>[eE][+-]?\d+)?$"
)
_QUALITATIVE_PHRASE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,40}$")
_DATE_LIKE = re.compile(
    r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}$|^\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}$"
)
_LABEL_LIKE = re.compile(r"^(?:page|barcode|labcode|sample|report|note)\b", re.IGNORECASE)


@dataclass
class NumberParse:
    is_number: bool
    value: Decimal | None = None
    text: str = ""
    precision: int = 0          # digits after the decimal point, as printed
    had_thousands_separator: bool = False
    reason: str = ""

    @property
    def is_integer(self) -> bool:
        return self.is_number and self.precision == 0

    def to_dict(self) -> dict:
        return {
            "is_number": self.is_number,
            "text": self.text,
            "value": str(self.value) if self.value is not None else None,
            "precision": self.precision,
            "had_thousands_separator": self.had_thousands_separator,
            "reason": self.reason,
        }


def parse_number(raw: str | None) -> NumberParse:
    """Parse a strictly numeric cell. Never coerces text into a number."""
    if raw is None:
        return NumberParse(False, reason="empty")
    text = raw.strip()
    if not text:
        return NumberParse(False, reason="empty")
    if _DATE_LIKE.match(text):
        return NumberParse(False, text=text, reason="looks like a date")
    if _LABEL_LIKE.match(text):
        return NumberParse(False, text=text, reason="looks like a label")

    match = _NUMBER.match(text)
    if not match:
        return NumberParse(False, text=text, reason="not a plain decimal number")

    digits = match.group("int").replace(",", "")
    frac = match.group("frac") or ""
    exp = match.group("exp") or ""
    precision = len(frac) - 1 if frac else 0
    sign = "-" if match.group("sign") == "-" else ""
    normalised = f"{sign}{digits}{frac}{exp}"
    try:
        value = Decimal(normalised)
    except InvalidOperation:
        return NumberParse(False, text=text, reason="decimal parse failed")
    return NumberParse(
        True,
        value=value,
        text=text,
        precision=precision,
        had_thousands_separator="," in match.group("int"),
        reason="ok",
    )


def looks_numeric(raw: str | None) -> bool:
    return parse_number(raw).is_number


def looks_qualitative(raw: str | None) -> bool:
    """Alphabetic phrase that could be a qualitative result (not a method word)."""
    if not raw:
        return False
    text = raw.strip()
    return bool(_QUALITATIVE_PHRASE.match(text))


# --------------------------------------------------------------------------
# Reference ranges
# --------------------------------------------------------------------------

_RANGE_BOTH = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(?P<high>\d+(?:\.\d+)?)"
)
_ONE_SIDED = re.compile(
    r"(?P<op><=|>=|<|>)\s*(?P<bound>\d+(?:\.\d+)?)"
    r"|(?P<word_op>less|fewer|greater|more)\s+than\s+(?P<word_bound>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_RATIO_RANGE = re.compile(r"\d+\s*:\s*\d+\s*-\s*\d+\s*:\s*\d+")
# Control-language and band tables are stratified. Population descriptors such
# as "Adults : 17-43" are NOT: the interval itself is unambiguous.
_STRATIFIED_HINT = re.compile(
    r"(?::\s*(?:normal|good|fair|poor|prediabet|diabet|decrease|control|high|low|"
    r"mild|moderate|severe))"
    r"|(?:\bcontrol\b|\bprediabet|\bdiabetic\b|\bpoor\b|\bfair\b)"
    r"|(?:below\s*\d|above\s*\d)",
    re.IGNORECASE,
)
_POPULATION_PREFIX = re.compile(
    r"^\s*(?:adults?|males?|females?|children|child|newborn|infant|"
    r"age\s*\d+\s*(?:-|to)?\s*\d*|\d+\s*(?:-|to)\s*\d+\s*(?:years|yrs|y))\s*[:\-]?\s*",
    re.IGNORECASE,
)
_INLINE_UNIT = re.compile(
    r"(?:mg/dl|mg/l|g/dl|gm/dl|u/l|iu/l|mmol/l|umol/l|µmol/l|meq/l|ng/ml|pg/ml|"
    r"ng/dl|µg/dl|ug/dl|µiu/ml|miu/ml|miu/l|seconds|sec|mm/hr|%|fl|pg|cells/hpf)",
    re.IGNORECASE,
)


def _clean(raw: str) -> str:
    text = raw.replace("\u00a0", " ")
    text = re.sub(r">\s*=", ">=", text)
    text = re.sub(r"<\s*=", "<=", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_reference_label(raw: str) -> bool:
    key = re.sub(r"[^a-z]", "", raw.lower())
    return key.startswith("biorefinterval") or key.startswith("referencerange") \
        or key in {"refrange", "referencerange"}


def parse_reference(raw: str | None) -> ReferenceRange:
    """Parse a reference-range cell into bounds *only when unambiguous*.

    Ambiguity is recorded, not resolved: stratified tables (``>=90: Normal``),
    ratio ranges (``9:1-23:1``), multiple intervals and descriptor-prefixed
    bands keep ``bounds=None`` and set ``stratified`` where appropriate.
    """
    if raw is None or not raw.strip():
        return ReferenceRange(text=None, parsed_confidence=0.0)

    text = _clean(raw)
    if text in {"-", "--", "---", "n/a", "N/A", "Nil", "nil"}:
        return ReferenceRange(text=text, parsed_confidence=0.0)

    if _RATIO_RANGE.search(text):
        # Ratio intervals ("9:1-23:1") are not numeric bounds in the same
        # dimension as the value; keep the text and flag for review.
        return ReferenceRange(text=text, stratified=True, parsed_confidence=0.0)

    # Multiple numerical intervals on one line => stratified band table.
    both = list(_RANGE_BOTH.finditer(text))
    ones = list(_ONE_SIDED.finditer(text))
    stratified = bool(_STRATIFIED_HINT.search(text)) or (len(both) + len(ones) > 1)
    pop_match = _POPULATION_PREFIX.match(text)
    population = pop_match.group(0).strip(" :-") if pop_match else None

    unit_hint = None
    match_unit = _INLINE_UNIT.search(text)
    if match_unit:
        unit_hint = match_unit.group(0)

    if stratified:
        # Try a single clean interval only if exactly one candidate exists.
        if len(both) == 1 and len(ones) == 0 and not _STRATIFIED_HINT.search(text):
            m = both[0]
            return ReferenceRange(
                text=text,
                low=float(m.group("low")),
                high=float(m.group("high")),
                unit_hint=unit_hint,
                parsed_confidence=0.9,
            )
        return ReferenceRange(text=text, stratified=True, unit_hint=unit_hint, parsed_confidence=0.0)

    if len(both) == 1 and not ones:
        m = both[0]
        low, high = float(m.group("low")), float(m.group("high"))
        if low > high:
            return ReferenceRange(text=text, unit_hint=unit_hint, parsed_confidence=0.0)
        # A population prefix ("Adults : 17-43") narrows the applicability but
        # the interval itself is still unambiguous.
        return ReferenceRange(
            text=text, low=low, high=high, unit_hint=unit_hint,
            low_text=m.group("low"), high_text=m.group("high"),
            parsed_confidence=1.0 if not population else 0.9,
        )

    if len(ones) == 1 and not both:
        m = ones[0]
        if m.group("word_op"):
            operator = "<" if m.group("word_op").lower() in ("less", "fewer") else ">"
            bound = float(m.group("word_bound"))
        else:
            operator = m.group("op")
            bound = float(m.group("bound"))
        if operator in ("<", "<="):
            return ReferenceRange(
                text=text, high=bound, high_inclusive=(operator == "<="),
                operator=operator, unit_hint=unit_hint,
                high_text=m.group("word_bound") or m.group("bound"),
                parsed_confidence=1.0,
            )
        return ReferenceRange(
            text=text, low=bound, low_inclusive=(operator == ">="),
            operator=operator, unit_hint=unit_hint,
            low_text=m.group("word_bound") or m.group("bound"),
            parsed_confidence=1.0,
        )

    if both or ones:
        return ReferenceRange(text=text, stratified=True, unit_hint=unit_hint, parsed_confidence=0.0)

    # No digits at all: a qualitative reference (e.g. "Absent", "Pale Yellow").
    if _QUALITATIVE_PHRASE.match(text):
        return ReferenceRange(text=text, qualitative=text, parsed_confidence=0.5,
                              unit_hint=unit_hint)
    return ReferenceRange(text=text, parsed_confidence=0.0)


def in_reference(value: Decimal | None, reference: ReferenceRange) -> bool | None:
    """Deterministic comparison against parsed bounds.

    Returns ``None`` when the range is not parsed numerically. Never used to
    modify a value — only to describe it.
    """
    if value is None:
        return None
    low_ok = reference.low is None
    high_ok = reference.high is None
    if reference.low is not None:
        low_ok = value >= Decimal(str(reference.low)) if reference.low_inclusive \
            else value > Decimal(str(reference.low))
    if reference.high is not None:
        high_ok = value <= Decimal(str(reference.high)) if reference.high_inclusive \
            else value < Decimal(str(reference.high))
    if reference.low is None and reference.high is None:
        return None
    return bool(low_ok and high_ok)
