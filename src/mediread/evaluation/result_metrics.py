"""Evaluation of structured laboratory results against verified ground truth.

Matching is per page and one-to-one: a ground-truth row is matched to at most one
extracted result, using test-name similarity (normalised equality first, then a
character-bigram Dice score) and, on ties, row position. Unmatched ground-truth
rows are misses; unmatched results are false positives.

The metrics are deliberately separated into three groups:

1. **Coverage** — did we find the right rows (row precision/recall)?
2. **Field accuracy** — are the values, units, ranges and qualitative results
   exactly what the page says?
3. **Safety** — of the fields we marked ``verified``, how many are wrong, and of
   the fields that *are* wrong, how many were flagged?

Group 3 is the one that matters for the product: a wrong value marked verified is
a silent failure, while a wrong value marked ``requires_review`` is the system
working.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..structured.text import parse_number
from ..structured import vocabulary as vocab

_WS = re.compile(r"\s+")


def norm_text(value: str | None) -> str:
    if value is None:
        return ""
    text = value.replace("\u00a0", " ").replace("µ", "u").replace("μ", "u")
    text = text.replace("³", "3").replace("²", "2").replace("^", "")
    return _WS.sub(" ", text).strip().lower()


def norm_value(value: str | None) -> str:
    text = norm_text(value)
    return text.replace(",", "").replace(" ", "")


def _bigrams(text: str) -> dict[str, int]:
    from collections import Counter

    compressed = text.replace(" ", "")
    if len(compressed) < 2:
        return Counter({compressed: 1}) if compressed else Counter()
    return Counter(compressed[i : i + 2] for i in range(len(compressed) - 1))


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ba, bb = _bigrams(a), _bigrams(b)
    overlap = sum((ba & bb).values())
    total = sum(ba.values()) + sum(bb.values())
    return 2.0 * overlap / total if total else 0.0


@dataclass
class FieldOutcome:
    field: str
    expected: Any
    actual: Any
    correct: bool
    verified: bool


@dataclass
class PairOutcome:
    gt_test: str
    result_test: str
    matched: bool
    fields: list[FieldOutcome] = field(default_factory=list)
    wrong_assignment: bool = False
    decimal_corruption: bool = False


@dataclass
class PageOutcome:
    report_id: str
    page: int
    gt_rows: int
    extracted_rows: int
    matched: int
    pairs: list[PairOutcome] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "page": self.page,
            "gt_rows": self.gt_rows,
            "extracted_rows": self.extracted_rows,
            "matched": self.matched,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "fields": [
                {
                    "test": p.gt_test,
                    "result_test": p.result_test,
                    "field": f.field,
                    "expected": f.expected,
                    "actual": f.actual,
                    "correct": f.correct,
                    "verified": f.verified,
                }
                for p in self.pairs
                for f in p.fields
            ],
        }


def _field_value(result, name: str):
    if name == "value":
        return result.value.raw
    if name == "unit":
        return result.unit.raw
    if name == "reference":
        return result.reference.raw
    if name == "qualitative":
        return result.qualitative.raw if result.qualitative else None
    return None


def _field_status(result, name: str) -> str:
    if name == "qualitative":
        return result.qualitative.status.value if result.qualitative else "missing"
    return getattr(result, name).status.value


def _unit_equal(expected: str | None, actual: str | None) -> bool:
    if expected is None or actual is None:
        return expected is actual
    if norm_text(expected) == norm_text(actual):
        return True
    expected_match = vocab.match_unit(expected)
    actual_match = vocab.match_unit(actual)
    if expected_match.canonical and actual_match.canonical:
        return expected_match.canonical == actual_match.canonical
    return False


def _value_equal(expected: str | None, actual: str | None) -> bool:
    if expected is None or actual is None:
        return expected is actual
    return norm_value(expected) == norm_value(actual)


def _reference_equal(expected: str | None, actual: str | None, reference_kind: str) -> bool:
    if reference_kind in ("stratified", "none"):
        return True  # excluded from scoring; see caller
    if expected is None or actual is None:
        return expected is actual
    return norm_text(expected) == norm_text(actual)


def _is_decimal_corruption(expected: str | None, actual: str | None) -> bool:
    if not expected or not actual or expected == actual:
        return False
    digits_e = re.sub(r"\D", "", expected)
    digits_a = re.sub(r"\D", "", actual)
    return bool(digits_e) and digits_e == digits_a and ("." in expected) != ("." in actual)


def evaluate_page(report_id: str, page: int, gt_rows: list[dict], results: list) -> PageOutcome:
    outcome = PageOutcome(
        report_id=report_id,
        page=page,
        gt_rows=len(gt_rows),
        extracted_rows=len(results),
        matched=0,
    )
    if not gt_rows:
        outcome.false_positives = [r.test.raw or "" for r in results]
        return outcome

    # Candidate pairs by test-name similarity.
    candidates: list[tuple[float, int, int]] = []
    for gi, gt in enumerate(gt_rows):
        gt_key = norm_text(gt["test"])
        for ri, result in enumerate(results):
            score = similarity(gt_key, norm_text(result.test.raw or ""))
            if score >= 0.86:
                candidates.append((score, gi, ri))
    candidates.sort(reverse=True)

    used_gt: set[int] = set()
    used_result: set[int] = set()
    value_pool = {norm_value(g["value"]) for g in gt_rows if g.get("value")}

    for score, gi, ri in candidates:
        if gi in used_gt or ri in used_result:
            continue
        used_gt.add(gi)
        used_result.add(ri)
        outcome.matched += 1
        gt = gt_rows[gi]
        result = results[ri]
        pair = PairOutcome(gt_test=gt["test"], result_test=result.test.raw or "", matched=True)

        fields: list[tuple[str, Any, Any, bool]] = []
        fields.append(
            ("value", gt.get("value"), _field_value(result, "value"),
             _value_equal(gt.get("value"), _field_value(result, "value")))
        )
        fields.append(
            ("unit", gt.get("unit"), _field_value(result, "unit"),
             _unit_equal(gt.get("unit"), _field_value(result, "unit")))
        )
        if gt.get("reference_kind") not in ("stratified", "none"):
            fields.append(
                ("reference", gt.get("reference"), _field_value(result, "reference"),
                 _reference_equal(gt.get("reference"), _field_value(result, "reference"),
                                  gt.get("reference_kind", "numeric")))
            )
        if gt.get("kind") == "qualitative":
            fields.append(
                ("qualitative", gt.get("qualitative"),
                 result.qualitative.raw if result.qualitative else None,
                 norm_text(gt.get("qualitative")) == norm_text(
                     result.qualitative.raw if result.qualitative else None))
            )

        for name, expected, actual, correct in fields:
            status = _field_status(result, name)
            pair.fields.append(
                FieldOutcome(
                    field=name, expected=expected, actual=actual, correct=correct,
                    verified=status == "verified",
                )
            )

        # Dangerous cases.
        actual_value = _field_value(result, "value")
        if not _value_equal(gt.get("value"), actual_value):
            if _is_decimal_corruption(gt.get("value"), actual_value):
                pair.decimal_corruption = True
            elif actual_value and norm_value(actual_value) in value_pool:
                pair.wrong_assignment = True
        outcome.pairs.append(pair)

    outcome.false_negatives = [gt_rows[i]["test"] for i in range(len(gt_rows)) if i not in used_gt]
    outcome.false_positives = [results[i].test.raw or "" for i in range(len(results)) if i not in used_result]
    return outcome


@dataclass
class Aggregate:
    pages: int = 0
    gt_rows: int = 0
    extracted_rows: int = 0
    matched: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    fields: dict[str, dict[str, int]] = field(default_factory=dict)
    wrong_assignment: int = 0
    decimal_corruption: int = 0
    verified_wrong: int = 0
    flagged_wrong: int = 0
    wrong_total: int = 0

    def to_dict(self) -> dict[str, Any]:
        precision = self.matched / self.extracted_rows if self.extracted_rows else 0.0
        recall = self.matched / self.gt_rows if self.gt_rows else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        fields = {}
        for name, counts in self.fields.items():
            total = counts.get("total", 0)
            correct = counts.get("correct", 0)
            verified = counts.get("verified", 0)
            verified_correct = counts.get("verified_correct", 0)
            fields[name] = {
                "total_scored": total,
                "correct": correct,
                "accuracy": round(correct / total, 4) if total else None,
                "verified": verified,
                "verified_precision": round(verified_correct / verified, 4) if verified else None,
                "flagged": counts.get("flagged", 0),
            }
        return {
            "pages": self.pages,
            "gt_rows": self.gt_rows,
            "extracted_rows": self.extracted_rows,
            "matched": self.matched,
            "row_precision": round(precision, 4),
            "row_recall": round(recall, 4),
            "row_f1": round(f1, 4),
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "wrong_assignment_errors": self.wrong_assignment,
            "decimal_corruption_errors": self.decimal_corruption,
            "wrong_fields_total": self.wrong_total,
            "wrong_fields_marked_verified": self.verified_wrong,
            "wrong_fields_flagged": self.flagged_wrong,
            "uncertainty_capture_rate": (
                round(self.flagged_wrong / self.wrong_total, 4) if self.wrong_total else None
            ),
            "fields": fields,
        }


def aggregate(outcomes: list[PageOutcome]) -> Aggregate:
    total = Aggregate(pages=len(outcomes))
    for outcome in outcomes:
        total.gt_rows += outcome.gt_rows
        total.extracted_rows += outcome.extracted_rows
        total.matched += outcome.matched
        total.false_positives += len(outcome.false_positives)
        total.false_negatives += len(outcome.false_negatives)
        for pair in outcome.pairs:
            if pair.wrong_assignment:
                total.wrong_assignment += 1
            if pair.decimal_corruption:
                total.decimal_corruption += 1
            for field_outcome in pair.fields:
                bucket = total.fields.setdefault(
                    field_outcome.field,
                    {"total": 0, "correct": 0, "verified": 0, "verified_correct": 0, "flagged": 0},
                )
                bucket["total"] += 1
                bucket["correct"] += int(field_outcome.correct)
                if field_outcome.verified:
                    bucket["verified"] += 1
                    bucket["verified_correct"] += int(field_outcome.correct)
                if not field_outcome.correct:
                    total.wrong_total += 1
                    if field_outcome.verified:
                        total.verified_wrong += 1
                    else:
                        bucket["flagged"] += 1
                        total.flagged_wrong += 1
    return total


def load_ground_truth(root: str | Path) -> dict[tuple[str, int], dict]:
    """Load annotated pages, carrying the development/holdout split."""
    root = Path(root)
    pages: dict[tuple[str, int], dict] = {}
    for path in sorted(root.glob("*_p*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("split", "development")
        pages[(data["report_id"], int(data["page"]))] = data
    return pages


def group_by_split(
    outcomes: list[PageOutcome], ground_truth: dict[tuple[str, int], dict]
) -> dict[str, list[PageOutcome]]:
    grouped: dict[str, list[PageOutcome]] = {}
    for outcome in outcomes:
        split = ground_truth.get((outcome.report_id, outcome.page), {}).get("split", "development")
        grouped.setdefault(split, []).append(outcome)
    return grouped


def evaluate_document(result_document, ground_truth: dict[tuple[str, int], dict]) -> list[PageOutcome]:
    outcomes: list[PageOutcome] = []
    by_page: dict[int, list] = {}
    for result in result_document.results:
        by_page.setdefault(result.page, []).append(result)
    for (report_id, page), gt in ground_truth.items():
        if report_id != result_document.report_id:
            continue
        outcomes.append(evaluate_page(report_id, page, gt["rows"], by_page.get(page, [])))
    return outcomes
