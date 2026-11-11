"""OCR evaluation metrics, weighted towards what is dangerous in a lab report.

Generic CER/WER treat "13.5" -> "135" as a small edit. In MediRead that is a
wrong measurement, so the metric set is layered:

* ``cer`` / ``wer``            — overall text quality (sanity, comparability).
* ``numeric_*``                — per-token numeric agreement: exact, decimal
                                 error, digit error, missing, spurious.
* ``unit_*``                   — unit-token agreement.
* ``range_*``                  — reference-range agreement (``4.0-10.0``, ``< 5``).
* ``table_row_recall``         — share of reference rows whose *value* appears.

A "decimal error" is a numeric token that is numerically identical to the
reference after removing separators but differs in where the decimal point sits
(e.g. ``13.5`` vs ``135``, ``0.58`` vs ``058``). Those are the silent-corruption
cases the product must never ship.

Numbers are never normalised to "fix" a value: comparison is exact-string first,
then a structured check to classify *why* it differs.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

# A numeric token: integers, decimals, optionally signed, with thousands
# separators. Deliberately does not swallow unit characters.
# Deliberately does not accept a leading sign or a trailing comparison operator.
# In a laboratory sentence "0.9 - 2" the hyphen is a range separator, not a
# negative sign, and "< 0.3" is a bound, not a measurement; treating either as
# part of the number creates phantom mismatches that hide real ones. Negative
# measurements are vanishingly rare in this domain and are documented as a
# limitation.
NUMBER_RE = re.compile(
    r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])"
    r"|(?<![\w.])\d+(?:\.\d+)?(?![\w])"
)
# Reference ranges: "4.0-10.0", "< 5", "> 90", "0.8 - 1.2", "up to 5".
RANGE_RE = re.compile(
    r"(?<!\w)(?:[<>]\s*)?\d+(?:\.\d+)?\s*(?:-|to|–)\s*\d+(?:\.\d+)?(?!\w)"
    r"|(?<!\w)[<>]\s*\d+(?:\.\d+)?(?!\w)"
)
UNIT_TOKENS = {
    "g/dl", "gm/dl", "mg/dl", "mg/l", "g/l", "u/l", "iu/l", "u/ml", "iu/ml",
    "mmol/l", "umol/l", "mol/l", "meq/l", "ng/ml", "pg/ml", "ng/dl",
    "pg", "fl", "ul", "ml", "ml/min", "ml/min/1.73", "miu/l", "uiu/ml", "miu/ml", "mm/hr",
    "mmhg", "sec", "seconds", "ratio", "index", "%", "cells/hpf", "cells/lpf",
    "103/ul", "106/ul", "x103/ul", "x106/ul", "l/l", "fmol/l", "pmol/l",
    "nmol/l", "ug/dl", "ug/l", "copies/ml", "titre", "units", "meq", "kpa",
    "mm", "cm", "pq",
}

# The source reports contain a small number of the laboratory's own typos and
# font-encoding substitutions (e.g. MCH printed as "pq" instead of "pg"). These
# are normalised on both sides so an engine is not penalised for reading what is
# printed, and a typo is not counted as an OCR error.
_UNIT_ALIASES = {
    "pq": "pg",          # source typo for pg (verified on the rendered page)
    "gm/dl": "g/dl",     # same unit, two spellings in this lab's output
    "x103/ul": "103/ul",  # "X 10^3/µL" is often read with the multiplier split off
    "x106/ul": "106/ul",
}


def normalise_unit_text(text: str) -> str:
    """Lowercase, unify micro/superscript glyphs, drop spaces and carets."""
    lowered = text.lower()
    for source, target in (("µ", "u"), ("μ", "u"), ("³", "3"), ("²", "2"), ("×", "x"), ("^", "")):
        lowered = lowered.replace(source, target)
    return re.sub(r"\s+", "", lowered)


_NORMALISED_UNITS = sorted(
    {normalise_unit_text(u) for u in UNIT_TOKENS}, key=len, reverse=True
)
# Spaces are removed before matching, so a unit may be glued to the number or to
# the preceding "x" (``6.02x103/ul``). Only a preceding *letter* rules a match
# out; digits must not, or every unit after a bare number would be missed.
UNIT_RE = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(u) for u in _NORMALISED_UNITS) + r")(?![a-z])"
)
_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Whitespace-normalised text used for CER/WER. Characters are untouched."""
    return _WS.sub(" ", text.replace("\u00a0", " ")).strip()


def _levenshtein(a: list[str] | str, b: list[str] | str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            insert = previous[j] + 1
            delete = current[j - 1] + 1
            substitute = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    ref = normalise(reference)
    hyp = normalise(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


def wer(reference: str, hypothesis: str) -> float:
    ref = normalise(reference).split()
    hyp = normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return _levenshtein(ref, hyp) / len(ref)


# Numbers that belong to a unit expression, not to a measurement:
# "X 10^3/µL", "10⁶/µL", "mL/min/1.73 m2". Counting these as measurements
# inflates the numeric denominator and turns a superscript misread into a
# "wrong value", hiding real measurement errors.
_UNIT_EXPRESSION = re.compile(
    r"(?:x\s*)?10\s*[\^³]?\s*[36]\s*/\s*[\u00b5u]?l"
    r"|ml\s*/\s*min\s*/\s*1\.73"
    r"|1\.73\s*m2",
    re.IGNORECASE,
)


def strip_unit_expressions(text: str) -> str:
    return _UNIT_EXPRESSION.sub(" ", text)


def numbers(text: str) -> list[str]:
    return [m.group(0).replace(" ", "").replace(",", "") for m in NUMBER_RE.finditer(text)]


def units(text: str) -> list[str]:
    normalised = normalise_unit_text(text)
    return [_UNIT_ALIASES.get(m.group(1), m.group(1)) for m in UNIT_RE.finditer(normalised)]


def ranges(text: str) -> list[str]:
    return [_WS.sub("", m.group(0)) for m in RANGE_RE.finditer(text)]


def _decimal_pattern(token: str) -> str:
    """``13.5`` -> ``DD.D``; ``135`` -> ``DDD``; used to compare decimal structure."""
    return "".join("D" if ch.isdigit() else "." for ch in token)


def _same_value_ignoring_decimal(a: str, b: str) -> bool:
    digits_a = re.sub(r"\D", "", a)
    digits_b = re.sub(r"\D", "", b)
    return bool(digits_a) and digits_a == digits_b and (("." in a) != ("." in b))


@dataclass
class TokenErrors:
    reference_count: int = 0
    hypothesis_count: int = 0
    exact_matches: int = 0
    missing: list[str] = field(default_factory=list)
    spurious: list[str] = field(default_factory=list)
    decimal_errors: list[tuple[str, str]] = field(default_factory=list)
    digit_errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def recall(self) -> float | None:
        """``None`` when the reference has no tokens of this type.

        Returning 0.0 for "no units on this page" would drag down the mean and
        invent a failure that did not happen.
        """
        if self.reference_count == 0:
            return None
        return self.exact_matches / self.reference_count

    def to_dict(self) -> dict:
        return {
            "reference_count": self.reference_count,
            "hypothesis_count": self.hypothesis_count,
            "exact_matches": self.exact_matches,
            "recall": None if self.recall is None else round(self.recall, 4),
            "missing": self.missing[:20],
            "spurious": self.spurious[:20],
            "decimal_errors": [list(pair) for pair in self.decimal_errors[:20]],
            "digit_errors": [list(pair) for pair in self.digit_errors[:20]],
            "decimal_error_count": len(self.decimal_errors),
            "digit_error_count": len(self.digit_errors),
            "missing_count": len(self.missing),
            "spurious_count": len(self.spurious),
        }


def compare_tokens(reference_tokens: list[str], hypothesis_tokens: list[str]) -> TokenErrors:
    """Order-aware comparison using a multiset alignment, then error typing.

    Unmatched reference/hypothesis tokens are paired by similarity so that a
    wrong digit is reported as a digit error rather than as one missing and one
    spurious token.
    """
    ref_counter = Counter(reference_tokens)
    hyp_counter = Counter(hypothesis_tokens)
    exact = sum((ref_counter & hyp_counter).values())

    remaining_ref: list[str] = []
    for token, count in (ref_counter - hyp_counter).items():
        remaining_ref.extend([token] * count)
    remaining_hyp: list[str] = []
    for token, count in (hyp_counter - ref_counter).items():
        remaining_hyp.extend([token] * count)

    errors = TokenErrors(reference_count=len(reference_tokens), hypothesis_count=len(hypothesis_tokens))
    errors.exact_matches = exact

    used_hyp: set[int] = set()
    for ref_token in remaining_ref:
        best_index = -1
        best_score = -1.0
        for index, hyp_token in enumerate(remaining_hyp):
            if index in used_hyp:
                continue
            score = _similarity(ref_token, hyp_token)
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and best_score >= 0.5:
            used_hyp.add(best_index)
            hyp_token = remaining_hyp[best_index]
            if _same_value_ignoring_decimal(ref_token, hyp_token):
                errors.decimal_errors.append((ref_token, hyp_token))
            else:
                errors.digit_errors.append((ref_token, hyp_token))
        else:
            errors.missing.append(ref_token)

    errors.spurious = [t for i, t in enumerate(remaining_hyp) if i not in used_hyp]
    return errors


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    distance = _levenshtein(a, b)
    return 1.0 - distance / max(len(a), len(b))


def compare_units(reference: str, hypothesis: str) -> TokenErrors:
    return compare_tokens(units(reference), units(hypothesis))


def compare_ranges(reference: str, hypothesis: str) -> TokenErrors:
    return compare_tokens(ranges(reference), ranges(hypothesis))


def score_page(reference: str, hypothesis: str) -> dict:
    """Full metric bundle for one page."""
    numeric = compare_tokens(
        numbers(strip_unit_expressions(reference)),
        numbers(strip_unit_expressions(hypothesis)),
    )
    unit = compare_units(reference, hypothesis)
    range_errors = compare_ranges(reference, hypothesis)
    ref_rows = [line for line in reference.splitlines() if line.strip()]
    hyp_text = normalise(hypothesis)
    matched_rows = 0
    for row in ref_rows:
        row_numbers = numbers(row)
        if not row_numbers:
            continue
        if all(n in hyp_text for n in row_numbers):
            matched_rows += 1
    rows_with_numbers = sum(1 for row in ref_rows if numbers(row))
    return {
        "cer": round(cer(reference, hypothesis), 4),
        "wer": round(wer(reference, hypothesis), 4),
        "characters_reference": len(normalise(reference)),
        "words_reference": len(normalise(reference).split()),
        "numeric": numeric.to_dict(),
        "units": unit.to_dict(),
        "ranges": range_errors.to_dict(),
        "table_row_recall": round(matched_rows / rows_with_numbers, 4) if rows_with_numbers else None,
    }


@dataclass
class Aggregate:
    pages: int = 0
    cer: float = 0.0
    wer: float = 0.0
    numeric_recall: float = 0.0
    unit_recall: float = 0.0
    range_recall: float = 0.0
    decimal_errors: int = 0
    digit_errors: int = 0
    missing_numbers: int = 0
    spurious_numbers: int = 0

    def to_dict(self) -> dict:
        return {
            "pages": self.pages,
            "cer_mean": round(self.cer, 4),
            "wer_mean": round(self.wer, 4),
            "numeric_recall": round(self.numeric_recall, 4),
            "unit_recall": round(self.unit_recall, 4),
            "range_recall": round(self.range_recall, 4),
            "decimal_errors": self.decimal_errors,
            "digit_errors": self.digit_errors,
            "missing_numbers": self.missing_numbers,
            "spurious_numbers": self.spurious_numbers,
        }


def aggregate(page_scores: list[dict]) -> Aggregate:
    """Mean metrics over pages; counts are summed because each is an incident."""
    if not page_scores:
        return Aggregate()
    total = Aggregate(pages=len(page_scores))
    for score in page_scores:
        total.cer += score["cer"]
        total.wer += score["wer"]
        total.numeric_recall += score["numeric"]["recall"] or 0.0
        total.unit_recall += score["units"]["recall"] or 0.0
        total.range_recall += score["ranges"]["recall"] or 0.0
        total.decimal_errors += score["numeric"]["decimal_error_count"]
        total.digit_errors += score["numeric"]["digit_error_count"]
        total.missing_numbers += score["numeric"]["missing_count"]
        total.spurious_numbers += score["numeric"]["spurious_count"]
    n = float(len(page_scores))
    total.cer /= n
    total.wer /= n
    total.numeric_recall /= n
    total.unit_recall /= n
    total.range_recall /= n
    return total


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval — reported because the sample is tiny.

    With a handful of pages, a point estimate hides that the true rate may be
    materially different; the interval makes the uncertainty explicit.
    """
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return ((centre - margin) / denominator, (centre + margin) / denominator)
