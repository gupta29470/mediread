"""Privacy helpers: everything printed or persisted passes through here.

The corpus is real patient material. Two rules are enforced in code:

1. Raw report text never reaches logs, console output or JSON artefacts written
   to disk unless the caller explicitly opts in *and* the process is local.
   The normal pipeline records structural facts (counts, boxes, confidences)
   and laboratory content only.
2. Every diagnostic string passes through :func:`redact_text`, which masks
   direct and quasi identifiers (names, ages, IDs, phone numbers, e-mail
   addresses, dates, addresses) while preserving laboratory content (test
   names, values, units, reference ranges). Masking a reference range would
   make extraction bugs undebuggable, so the patterns are written to avoid
   numeric ranges: dates require a plausible four-digit year or a month name.

False positives cost debugging context; false negatives leak patient data, so
the defaults are conservative.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Iterable

MASK = "[REDACTED]"
NAME_MASK = "[NAME]"

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_URL = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
# Long digit runs: accession numbers, MRNs, barcodes, phone numbers.
_LONG_NUMBER = re.compile(r"\b\d[\d /\-]{6,}\d\b")
# Explicit identifier labels: the whole value is an identifier whatever its shape.
_ID_LABEL = re.compile(
    r"(?P<label>(?:lab\s*code|labcode|accession(?:\s*no\.?)?|sample\s*(?:id|no\.?)|"
    r"barcode|reg(?:istration)?\.?\s*(?:no\.?|number)|patient\s*id|uhid|mrn|"
    r"visit\s*(?:id|no\.?))\s*[:#]?\s*)(?P<value>\S+)",
    re.IGNORECASE,
)
# Dates: must carry a 4-digit year or a month name. Reference ranges such as
# "0.8-1.2" or "11.0 - 13.1" must never match.
_YEAR = r"(?:19|20)\d{2}"
_DATE = re.compile(
    rf"(?:\b\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]{_YEAR}\b"
    rf"|\b{_YEAR}[/.\-]\d{{1,2}}[/.\-]\d{{1,2}}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+{_YEAR}\b"
    rf"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{{1,2}},?\s+{_YEAR}\b)",
    re.IGNORECASE,
)
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b")
# Age/sex markers such as "(49Y/F)" or "20 Y / M" are quasi-identifiers.
_AGE_SEX = re.compile(r"\(?\b\d{1,3}\s*[YyMmDd]\s*/\s*[MFmf]\b\)?")

# "Name  : X", "Report for X", "Ref. By : X" — value runs to end of line, a
# double space, or an opening parenthesis.
_NAME_LABEL = re.compile(
    r"(?P<label>\b(?:patient\s*name|patient|name|report\s*(?:for|of)|ref(?:erred)?\.?\s*by|"
    r"doctor|dr\.?|consultant|physician|pathologist)\s*[:#]?\s*)"
    r"(?P<value>[A-Za-z][A-Za-z .'\-]{1,48})",
    re.IGNORECASE,
)

# Tokens that can follow a name-like label without being a person's name.
_NOT_A_NAME = {
    "technology", "value", "values", "unit", "units", "result", "results",
    "test", "tests", "method", "methods", "range", "ranges", "reference",
    "interval", "status", "date", "time", "sample", "type", "collected",
    "received", "released", "barcode", "labcode", "code", "no", "id", "sex",
    "age", "gender", "self", "complete", "available", "report", "profile",
    "and", "of", "the", "a", "an", "total", "direct", "indirect", "serum",
    "blood", "urine", "sodium", "potassium", "chloride", "calcium",
    "haemoglobin", "hemoglobin", "glucose", "creatinine", "bilirubin",
    "albumin", "protein", "cholesterol", "triglycerides", "thyroid",
}

# Address-like lines: Indian lab reports put the collection address in caps.
_ADDRESS = re.compile(
    r"\b(?:society|nagar|road|street|lane|apartment|co-?op(?:erative)?|housing|"
    r"plot|flat|sector|building|tower|block|marg|colony|village|taluka|district|"
    r"pin\s*code|pin)\b",
    re.IGNORECASE,
)


def report_key(filename: str) -> str:
    """Stable, non-reversible pseudo-identifier for a source file.

    Filenames in the dataset are already opaque hashes; this helper makes the
    contract explicit so callers cannot start logging names.
    """
    return hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]


def redact_text(text: str) -> str:
    """Mask direct and quasi identifiers in a block of report text."""
    if not text:
        return text
    return "\n".join(_redact_line(line) for line in text.splitlines())


def _redact_line(line: str) -> str:
    if not line.strip():
        return line

    line = _EMAIL.sub(MASK, line)
    line = _URL.sub(MASK, line)
    line = _ID_LABEL.sub(lambda m: f"{m.group('label')}{MASK}", line)
    line = _NAME_LABEL.sub(_mask_name, line)
    line = _AGE_SEX.sub(MASK, line)
    line = _DATE.sub(MASK, line)
    line = _TIME.sub(MASK, line)
    line = _LONG_NUMBER.sub(_mask_long_number, line)
    if _ADDRESS.search(line) and sum(c.isalpha() for c in line) > 12:
        # Keep the keyword-free shape so layout is still visible.
        return re.sub(r"[A-Za-z]{2,}", "*", line) if line.isupper() else MASK
    return line


def _mask_long_number(match: re.Match[str]) -> str:
    """Mask only identifiers: at least seven digits.

    A reference range such as ``45 - 129`` is eight characters but only five
    digits; masking it would destroy laboratory content that debugging depends
    on. Accession numbers and phone numbers carry seven or more digits.
    """
    digits = sum(ch.isdigit() for ch in match.group(0))
    return MASK if digits >= 7 else match.group(0)


def _mask_name(match: re.Match[str]) -> str:
    value = match.group("value").strip()
    first = re.split(r"[\s,;/]+", value)[0].lower().strip(".:")
    if not first:
        return match.group("label")
    if first in _NOT_A_NAME or first.isdigit():
        return match.group(0)
    # A single all-caps word is probably a value token, not a name, unless the
    # label explicitly asked for a person.
    if first.isupper() and " " not in value.strip():
        label = match.group("label").lower()
        if not any(k in label for k in ("name", "report", "ref", "doctor", "dr")):
            return match.group(0)
    return f"{match.group('label')}{NAME_MASK}"


def redact_rows(rows: Iterable[dict]) -> list[dict]:
    """Redact every string value in a list of flat records."""
    return [
        {k: (redact_text(v) if isinstance(v, str) else v) for k, v in row.items()}
        for row in rows
    ]


class RedactingFilter(logging.Filter):
    """Logging filter that masks identifiers in the formatted message."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact_text(message)
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO, stream=None) -> logging.Logger:
    """Configure a single redacting console handler for the package."""
    logger = logging.getLogger("mediread")
    logger.setLevel(level)
    logger.handlers.clear()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s :: %(message)s", "%H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger
