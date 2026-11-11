"""Evaluation metrics: CER/WER plus numeric, decimal, unit and range errors."""

from __future__ import annotations

import pytest

from mediread.evaluation.metrics import (
    aggregate,
    cer,
    compare_tokens,
    numbers,
    ranges,
    score_page,
    strip_unit_expressions,
    units,
    wer,
    wilson_interval,
)


def test_cer_identical_is_zero():
    assert cer("HAEMOGLOBIN 13.5 g/dL", "HAEMOGLOBIN 13.5 g/dL") == 0.0


def test_cer_detects_single_character():
    assert cer("ABCDEFGHIJ", "ABCDEFGHIX") == pytest.approx(0.1)


def test_cer_whitespace_insensitive():
    assert cer("A  B", "A B") == 0.0


def test_wer_counts_word_errors():
    assert wer("a b c d", "a b x d") == pytest.approx(0.25)


def test_numbers_extracts_decimals_and_ranges():
    assert numbers("65.63 U/L 45-129 < 0.3") == ["65.63", "45", "129", "0.3"]


def test_number_does_not_swallow_comparison_operator():
    assert numbers("< 0.3") == ["0.3"]
    assert numbers("0.9 - 2") == ["0.9", "2"]


def test_number_does_not_split_leading_dot():
    assert numbers("0.58 mg/dL") == ["0.58"]


def test_unit_expressions_are_not_measurements():
    assert numbers(strip_unit_expressions("RBC 4.39 X 10^6/uL 3.8-4.8")) == ["4.39", "3.8", "4.8"]
    assert numbers(strip_unit_expressions("eGFR 112 mL/min/1.73 m2")) == ["112"]


def test_decimal_error_is_classified():
    errors = compare_tokens(["13.5"], ["135"])
    assert errors.decimal_errors == [("13.5", "135")]
    assert errors.digit_errors == []
    assert errors.missing == []


def test_digit_error_is_classified():
    errors = compare_tokens(["0.58"], ["0.68"])
    assert errors.digit_errors == [("0.58", "0.68")]
    assert errors.decimal_errors == []


def test_missing_and_spurious():
    errors = compare_tokens(["1", "2"], ["1", "3"])
    assert errors.exact_matches == 1
    assert errors.missing == ["2"] or errors.digit_errors
    strict = compare_tokens(["1", "9.9"], ["1"])
    assert strict.missing == ["9.9"]


def test_units_normalised():
    assert units("X 10³ / µL") == ["103/ul"]
    assert units("µg/dL") == ["ug/dl"]
    assert units("gm/dL") == ["g/dl"]
    assert units("mIU/mL") == ["miu/ml"]


def test_units_typo_alias():
    # The source report prints "pq" for pg on one page; verified visually.
    assert units("21 pq") == ["pg"]


def test_ranges_extract():
    assert ranges("4.0 - 10.0") == ["4.0-10.0"]
    assert ranges("< 0.3") == ["<0.3"]
    assert ranges("45-129") == ["45-129"]


def test_score_page_perfect():
    reference = "TEST NAME VALUE UNITS REF\nHAEMOGLOBIN 13.5 g/dL 12.0-15.0"
    score = score_page(reference, reference)
    assert score["cer"] == 0.0
    assert score["numeric"]["recall"] == 1.0
    assert score["units"]["recall"] == 1.0
    assert score["ranges"]["recall"] == 1.0


def test_score_page_flags_decimal_error():
    reference = "HAEMOGLOBIN 13.5 g/dL 12.0-15.0"
    hypothesis = "HAEMOGLOBIN 135 g/dL 12.0-15.0"
    score = score_page(reference, hypothesis)
    assert score["numeric"]["decimal_error_count"] == 1
    assert ("13.5", "135") in [tuple(p) for p in score["numeric"]["decimal_errors"]]
    assert score["numeric"]["recall"] < 1.0


def test_aggregate_means_and_counts():
    scores = [
        score_page("A 1.0 B", "A 1.0 B"),
        score_page("A 1.0 B", "A 10 B"),
    ]
    agg = aggregate(scores)
    assert agg.pages == 2
    assert 0.0 < agg.cer < 1.0
    assert agg.decimal_errors == 1


def test_wilson_interval_bounds():
    low, high = wilson_interval(170, 170)
    assert 0.9 < low <= 1.0
    assert high == pytest.approx(1.0)
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_recall_none_when_no_reference_tokens():
    score = score_page("no units here", "no units here")
    assert score["units"]["recall"] is None
