"""Evaluation metrics and ground-truth integrity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.evaluation.result_metrics import (
    aggregate,
    evaluate_page,
    load_ground_truth,
    norm_text,
    similarity,
)
from mediread.structured.schema import (
    Evidence,
    Field,
    FieldStatus,
    LabResult,
    ReferenceRange,
    ValueKind,
)


class FakeResult:
    """Minimal stand-in for a LabResult used by metric tests."""

    def __init__(self, test, value, unit=None, reference=None, *, status="verified"):
        self.test = Field(raw=test, status=FieldStatus.VERIFIED)
        self.value = Field(raw=value, status=FieldStatus(status))
        self.unit = Field(raw=unit, status=FieldStatus.VERIFIED if unit else FieldStatus.MISSING)
        self.reference = Field(raw=reference, status=FieldStatus.VERIFIED)
        self.qualitative = None
        self.value_kind = ValueKind.NUMERIC


def gt_row(test, value, unit=None, reference=None, **kwargs):
    base = {
        "test": test, "value": value, "unit": unit, "reference": reference,
        "kind": "numeric", "reference_kind": "numeric", "qualitative": None,
    }
    base.update(kwargs)
    return base


def test_similarity_and_normalisation():
    assert norm_text("  HbA1c  ") == "hba1c"
    assert similarity("hemoglobin", "haemoglobin") > 0.8
    assert similarity("bilirubin total", "bilirubin direct") < 0.9


def test_row_match_and_value_accuracy():
    outcome = evaluate_page(
        "r", 1,
        [gt_row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0")],
        [FakeResult("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0")],
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["row_recall"] == 1.0
    assert stats["fields"]["value"]["accuracy"] == 1.0
    assert stats["wrong_fields_total"] == 0


def test_false_positive_and_negative():
    outcome = evaluate_page(
        "r", 1,
        [gt_row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0"), gt_row("PLATELET COUNT", "264")],
        [FakeResult("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0"), FakeResult("SODIUM", "140")],
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["false_positives"] == 1
    assert stats["false_negatives"] == 1
    assert stats["row_recall"] == 0.5


def test_decimal_corruption_detected_and_counted():
    outcome = evaluate_page(
        "r", 1, [gt_row("ALKALINE PHOSPHATASE", "65.63", "U/L", "45-129")],
        [FakeResult("ALKALINE PHOSPHATASE", "6563", "U/L", "45-129")],
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["decimal_corruption_errors"] == 1
    assert stats["fields"]["value"]["accuracy"] == 0.0


def test_wrong_value_assigned_to_wrong_test():
    results = [
        FakeResult("HEMOGLOBIN", "264", "g/dL", "12.0-15.0"),
        FakeResult("PLATELET COUNT", "9.2", "X 10³ / µL", "150-410"),
    ]
    outcome = evaluate_page(
        "r", 1,
        [gt_row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0"),
         gt_row("PLATELET COUNT", "264", "X 10³ / µL", "150-410")],
        results,
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["wrong_assignment_errors"] == 2


def test_verified_wrong_is_counted_separately():
    outcome = evaluate_page(
        "r", 1, [gt_row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0")],
        [FakeResult("HEMOGLOBIN", "9.3", "g/dL", "12.0-15.0", status="verified")],
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["wrong_fields_marked_verified"] >= 1
    assert stats["wrong_fields_flagged"] == 0


def test_flagged_wrong_is_not_a_silent_failure():
    outcome = evaluate_page(
        "r", 1, [gt_row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0")],
        [FakeResult("HEMOGLOBIN", "9.3", "g/dL", "12.0-15.0", status="requires_review")],
    )
    stats = aggregate([outcome]).to_dict()
    assert stats["wrong_fields_marked_verified"] == 0
    assert stats["uncertainty_capture_rate"] == 1.0


def test_stratified_reference_is_excluded_from_scoring():
    outcome = evaluate_page(
        "r", 1, [gt_row("eGFR", "112", "mL/min/1.73 m2", None, reference_kind="stratified")],
        [FakeResult("eGFR", "112", "mL/min/1.73 m2", ">= 90 : Normal")],
    )
    stats = aggregate([outcome]).to_dict()
    assert "reference" not in stats["fields"]


def test_ground_truth_files_are_well_formed():
    root = Path(__file__).resolve().parents[1] / "data" / "result_ground_truth"
    pages = load_ground_truth(root)
    if not pages:
        pytest.skip("no ground truth in this environment")
    splits = {data.get("split") for data in pages.values()}
    assert {"development", "holdout", "blind"} <= splits
    for (report_id, page), data in pages.items():
        assert data["rows"], f"{report_id} p{page} has no rows"
        for row in data["rows"]:
            assert row["test"]
            assert row["kind"] in {"numeric", "qualitative", "bound", "range", "text"}
            assert row["reference_kind"] in {"numeric", "qualitative", "stratified", "none", "ratio"}


def test_ground_truth_contains_no_identifiers():
    """The evaluation corpus must not carry patient data."""
    from mediread.privacy import redact_text

    root = Path(__file__).resolve().parents[1] / "data" / "result_ground_truth"
    for path in root.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["rows"]:
            for value in row.values():
                if isinstance(value, str):
                    assert redact_text(value) == value, f"identifier leaked in {path.name}: {value}"
