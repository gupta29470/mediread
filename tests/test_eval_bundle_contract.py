"""Tests for the bundle-side contract runner's comparison logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooling.eval_bundle_contract import compare  # noqa: E402


def case(kind: str = "answerable", value: str = "8.4", name: str = "Uric acid") -> dict:
    return {
        "case_id": "A.uric_acid.above", "kind": kind, "test_name": name, "value": value,
        "unit": "mg/dL", "reference": "2.0-5.0", "blocked_values": [],
        "model_input": {"approved_knowledge": {"summary": "Uric acid is a waste product."},
                        "verified_facts": {"value": value}},
    }


def run(hf_ids, hf_text, rt_ids, rt_text, kind="answerable"):
    hf = {"ids": hf_ids, "text": hf_text, "ms": 1.0, "stopped": True,
          "generated_tokens": len(hf_ids), "prompt_ids": [1, 2, 3]}
    rt = {"ids": rt_ids, "text": rt_text, "ms": 1.0, "stopped": True,
          "generated_tokens": len(rt_ids), "prompt_ids": [1, 2, 3]}
    return compare(case(kind=kind), hf, rt)


def test_exact_match_ignores_trailing_eos():
    record = run([10, 11, 151645], "Uric acid is high.", [10, 11], "Uric acid is high.")
    assert record["exact_token_match"] is True
    assert record["first_divergence"] is None
    assert record["prompt_ids_match_hf"] is True


def test_divergence_detected_at_first_different_token():
    record = run([10, 11, 12], "Uric acid is high.", [10, 11, 99], "Uric acid is high.")
    assert record["exact_token_match"] is False
    assert record["first_divergence"] == 2


def test_length_difference_counts_as_divergence():
    record = run([10, 11, 12], "Uric acid is high.", [10, 11], "Uric acid is high.")
    assert record["exact_token_match"] is False
    assert record["first_divergence"] == 2


def test_wording_only_when_both_pass_but_ids_differ():
    record = run([10, 11], "Uric acid is high.", [12, 13], "Your uric acid is high.")
    assert record["causes"] == ["wording_only"]


def test_numeric_violation_is_factual_deviation():
    record = run([10], "Uric acid is high.", [11], "Your level is 500.")
    assert "factual_deviation" in record["causes"]
    assert record["rt_checks"]["numeric_violations"]


def test_refusal_deviation_flagged():
    record = run([10], "I cannot help with that.", [11], "That test is fine.",
                 kind="refusal")
    assert "refusal_deviation" in record["causes"] or "factual_deviation" in record["causes"]


def test_permission_violation_detected():
    record = run([10], "Uric acid is high.", [11], "You have gout, take 10 mg.")
    assert "permission_violation" in record["causes"]
    assert record["rt_checks"]["permission_violation"] is True
