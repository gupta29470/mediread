"""Structured extraction: vocabulary, parsing, row assembly, validation.

Synthetic pages cover the layouts and edge cases the result schema must survive:
different column arrangements, multi-block tables, qualitative strips, missing
units, stratified ranges, prose between rows, and malformed input.

Real-corpus regression tests at the bottom use extraction artefacts produced by
the ingestion layer (no patient text is asserted, only laboratory content).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.structured import StructuredExtractionPipeline
from mediread.structured import vocabulary as vocab
from mediread.structured.schema import FieldStatus
from mediread.structured.text import (
    in_reference,
    looks_numeric,
    parse_number,
    parse_reference,
)
from mediread.structured.validate import aggregate_status, resolve_duplicates
from tests.conftest import (
    COLUMNS_4,
    COLUMNS_4_RANGE,
    COLUMNS_5,
    COLUMNS_URINE,
    DocBuilder,
    PageBuilder,
    build_page,
)


def run(page: dict):
    return StructuredExtractionPipeline().process(DocBuilder().add(page).build())


def one(page: dict):
    document = run(page)
    assert document.results, "expected at least one result"
    return document.results[0]


# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,canonical,status",
    [
        ("g/dL", "g/dL", vocab.UnitStatus.EXACT),
        ("gm/dL", "g/dL", vocab.UnitStatus.VARIANT),
        ("mg/dl", "mg/dL", vocab.UnitStatus.EXACT),
        ("X 10³ / µL", "10^3/µL", vocab.UnitStatus.VARIANT),
        ("µIU/mL", "µIU/mL", vocab.UnitStatus.EXACT),
        ("mL/min/1.73 m2", "mL/min/1.73 m²", vocab.UnitStatus.EXACT),
        ("cells/HPF", "cells/HPF", vocab.UnitStatus.EXACT),
        ("Cells/ul*", "cells/µL", vocab.UnitStatus.EXACT),
    ],
)
def test_unit_vocabulary(raw, canonical, status):
    match = vocab.match_unit(raw)
    assert match.status is status
    assert match.canonical == canonical


@pytest.mark.parametrize("raw", ["HL", "HIU/ML", "Hg/dL", "qm/dL", "pq"])
def test_ambiguous_units_are_not_resolved(raw):
    match = vocab.match_unit(raw)
    assert match.status is vocab.UnitStatus.AMBIGUOUS
    assert match.canonical is None
    assert match.alternatives


@pytest.mark.parametrize("raw", ["-", "--", "- --", "—", "N/A"])
def test_no_unit_markers(raw):
    assert vocab.match_unit(raw).status is vocab.UnitStatus.NONE


def test_unknown_unit_is_unknown_not_guessed():
    match = vocab.match_unit("furlongs/fortnight")
    assert match.status is vocab.UnitStatus.UNKNOWN
    assert match.canonical is None


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------


def test_decimal_precision_preserved():
    parsed = parse_number("65.63")
    assert parsed.is_number
    assert str(parsed.value) == "65.63"
    assert parsed.precision == 2


@pytest.mark.parametrize(
    "text,expected",
    [("0.58", "0.58"), ("5", "5"), ("-1.2", "-1.2"), ("1.2e3", "1.2E+3"), ("1,234", "1234")],
)
def test_number_forms(text, expected):
    parsed = parse_number(text)
    assert parsed.is_number
    assert str(parsed.value).upper() == expected.upper()


@pytest.mark.parametrize(
    "text", ["12/03/2024", "Page 5 of 10", "BV621560", "1.2.3", "65.63*", "N/A", "Nil"]
)
def test_non_numbers_rejected(text):
    assert not parse_number(text).is_number


def test_looks_numeric_guard():
    assert looks_numeric("13.5")
    assert not looks_numeric("PHOTOMETRY")


# --------------------------------------------------------------------------
# Reference ranges
# --------------------------------------------------------------------------


def test_range_bounds():
    ref = parse_reference("45-129")
    assert (ref.low, ref.high) == (45.0, 129.0)
    assert ref.parsed_confidence == 1.0


def test_range_with_spaces():
    ref = parse_reference("4.0 - 10.0")
    assert (ref.low, ref.high) == (4.0, 10.0)


def test_one_sided_bounds():
    assert parse_reference("< 0.3").high == 0.3
    assert parse_reference("> 90").low == 90
    assert parse_reference("Less than 30.2 U/ml").high == 30.2


def test_population_prefix_still_parses():
    ref = parse_reference("Adults : 17-43")
    assert (ref.low, ref.high) == (17.0, 43.0)
    assert ref.parsed_confidence == 0.9


def test_ratio_range_is_flagged():
    ref = parse_reference("9:1-23:1")
    assert ref.stratified
    assert ref.low is None and ref.high is None


def test_stratified_bands_are_flagged():
    ref = parse_reference("Below 5.7% : Normal | Below 6.5% : Good Control")
    assert ref.stratified
    assert ref.low is None


def test_qualitative_reference():
    ref = parse_reference("Pale Yellow")
    assert ref.qualitative == "Pale Yellow"


def test_in_reference_comparison():
    ref = parse_reference("4.0-10.0")
    assert in_reference(parse_number("6.02").value, ref) is True
    assert in_reference(parse_number("12").value, ref) is False


# --------------------------------------------------------------------------
# Rows, headings and sections
# --------------------------------------------------------------------------


def test_five_column_table():
    page = build_page(
        [{"test": "ALKALINE PHOSPHATASE", "method": "PHOTOMETRY", "value": "65.63",
          "unit": "U/L", "range": "45-129"}]
    )
    result = one(page)
    assert result.test.raw == "ALKALINE PHOSPHATASE"
    assert result.value.raw == "65.63"
    assert result.unit.raw == "U/L"
    assert result.reference.raw == "45-129"
    assert result.section == "Liver function"


def test_four_column_table_without_range_column():
    page = build_page(
        [{"test": "SODIUM", "method": "I.S.E", "value": "136.17", "unit": "mmol/L"}],
        columns=COLUMNS_4,
    )
    result = one(page)
    assert result.value.raw == "136.17"
    assert result.reference.status is FieldStatus.MISSING


def test_urine_observation_column():
    page = build_page(
        [{"test": "COLOUR", "value": "PALE YELLOW", "unit": "-", "range": "Pale Yellow"}],
        columns=COLUMNS_URINE,
        urinogram=True,
    )
    result = one(page)
    assert result.value.raw == "PALE YELLOW"
    assert result.value_kind.value == "qualitative"
    assert result.qualitative.raw == "PALE YELLOW"
    assert result.status is FieldStatus.VERIFIED


def test_single_letter_blood_group_is_qualitative():
    page = build_page(
        [{"test": "BLOOD GROUPING", "method": "AGGLUTINATION", "value": "B"}],
        columns=COLUMNS_4,
    )
    result = one(page)
    assert result.value.normalized == "B"
    assert result.status is FieldStatus.VERIFIED


def test_multiple_table_blocks_on_one_page():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "SODIUM"), (240.0, "I.S.E"), (350.0, "136.17"), (420.0, "mmol/L")])
    builder.row([(26.0, "TEST NAME"), (240.0, "VALUE"), (350.0, "UNITS"), (450.0, "Bio. Ref. Interval.")])
    builder.row([(26.0, "HEMOGLOBIN"), (240.0, "9.2"), (350.0, "g/dL"), (450.0, "12.0-15.0")])
    document = StructuredExtractionPipeline().process(DocBuilder().add(builder.page()).build())
    assert {r.test.raw for r in document.results} == {"SODIUM", "HEMOGLOBIN"}


def test_section_heading_attached():
    page = build_page(
        [
            {"heading": "Physical Examination"},
            {"test": "VOLUME", "value": "3", "unit": "mL", "range": "-"},
            {"heading": "Chemical Examination"},
            {"test": "URINARY PROTEIN", "value": "ABSENT", "unit": "mg/dL", "range": "Absent"},
        ],
        columns=COLUMNS_URINE,
        urinogram=True,
    )
    document = run(page)
    by_test = {r.test.raw: r for r in document.results}
    assert by_test["VOLUME"].section
    assert by_test["URINARY PROTEIN"].section


# --------------------------------------------------------------------------
# Row association edge cases
# --------------------------------------------------------------------------


def test_reference_on_following_line():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "PROTHROMBIN TIME"), (240.0, "PHOTO OPTICAL"), (350.0, "11.2"), (420.0, "Seconds")])
    builder.row([(26.0, "Bio. Ref. Interval. :")])
    builder.row([(26.0, "9.8-12.1 Seconds")])
    builder.row([(26.0, "Method : SCATTERED LIGHT")])
    result = one(builder.page())
    assert result.reference.raw == "9.8-12.1 Seconds"
    assert result.reference.status is FieldStatus.VERIFIED
    assert result.reference.parsed["low"] == 9.8


def test_multiline_test_name_with_value_below():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "HbA1c - (HPLC)")])
    builder.row([(240.0, "H.P.L.C"), (350.0, "5.3"), (420.0, "%")])
    result = one(builder.page())
    assert result.test.raw == "HbA1c - (HPLC)"
    assert result.value.raw == "5.3"
    assert result.unit.raw == "%"


def test_stratified_band_rows_attach_to_result():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "EST. GLOMERULAR FILTRATION RATE (eGFR)"), (240.0, "CALCULATED"),
                 (350.0, "112"), (420.0, "mL/min/1.73 m2")])
    builder.row([(26.0, "Bio. Ref. Interval. :-")])
    builder.row([(26.0, "> = 90 : Normal")])
    builder.row([(26.0, "60 - 89 : Mild Decrease")])
    builder.row([(26.0, "Method:- CKD-EPI")])
    document = run(builder.page())
    assert len(document.results) == 1
    result = document.results[0]
    assert "60 - 89" in (result.reference.raw or "")
    assert result.reference.status is FieldStatus.REQUIRES_REVIEW


def test_prose_and_method_rows_are_not_results():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "HAEMOGLOBIN"), (240.0, "PHOTOMETRY"), (350.0, "13.5"), (420.0, "g/dL")])
    builder.row([(26.0, "The above findings are suggestive of a trait and should be correlated clinically.")])
    builder.row([(26.0, "Method : photometric assay on an automated analyser")])
    document = run(builder.page())
    assert len(document.results) == 1
    assert document.results[0].test.raw == "HAEMOGLOBIN"


def test_nested_risk_band_rows_are_not_results():
    page = build_page(
        [
            {"test": "TOTAL CHOLESTEROL", "method": "PHOTOMETRY", "value": "113", "unit": "mg/dL", "range": "< 200"},
            {"test": "DESIRABLE <200", "value": "<100", "unit": "mg/dL"},
            {"test": "BORDERLINE HIGH 200-239", "value": "100-129", "unit": "mg/dL"},
        ]
    )
    document = run(page)
    assert [r.test.raw for r in document.results] == ["TOTAL CHOLESTEROL"]


def test_value_cell_that_swallowed_the_range():
    page = build_page(
        [{"test": "URINARY LEUCOCYTES (PUS CELLS)", "value": "8", "unit": "cells/HPF 0-5"}],
        columns=COLUMNS_4,
    )
    result = one(page)
    assert result.unit.raw == "cells/HPF"
    assert result.reference.raw == "0-5"


def test_qualitative_with_trailing_unit_marker():
    # Three columns give the free-text value room, as on the real urine page.
    page = build_page(
        [{"test": "CRYSTALS", "value": "CALCIUM OXALATE CRYSTALS -", "range": "Absent"}],
        columns={"test": 26.0, "value": 180.0, "range": 470.0},
    )
    result = one(page)
    assert result.value.raw == "CALCIUM OXALATE CRYSTALS"
    assert result.unit.raw == "-"


# --------------------------------------------------------------------------
# Field statuses and safety
# --------------------------------------------------------------------------


def test_clean_result_is_verified():
    page = build_page(
        [{"test": "HEMOGLOBIN", "method": "PHOTOMETRY", "value": "9.2",
          "unit": "g/dL", "range": "12.0-15.0"}]
    )
    assert one(page).status is FieldStatus.VERIFIED


def test_numeric_result_without_unit_is_never_verified():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2"}], columns=COLUMNS_4_RANGE)
    result = one(page)
    assert result.status is not FieldStatus.VERIFIED
    assert any("unit" in reason for reason in result.unit.reasons)


def test_ambiguous_unit_requires_review():
    page = build_page(
        [{"test": "MEAN CORPUSCULAR HEMOGLOBIN(MCH)", "value": "21", "unit": "pq", "range": "27.0-32.0"}]
    )
    result = one(page)
    assert result.unit.status is FieldStatus.REQUIRES_REVIEW
    assert result.unit.raw == "pq"          # preserved verbatim
    assert result.unit.normalized is None   # never silently resolved
    assert result.unit.alternatives


def test_bound_value_requires_review():
    page = build_page(
        [{"test": "SPECIFIC GRAVITY", "value": "< 1.003", "unit": "-", "range": "1.003-1.030"}]
    )
    result = one(page)
    assert result.value.status is FieldStatus.REQUIRES_REVIEW
    assert result.value.parsed["bound_operator"] == "<"


def test_value_range_requires_review():
    page = build_page([{"test": "EPITHELIAL CELLS", "value": "1-2", "unit": "-", "range": "2-3"}])
    result = one(page)
    assert result.value.status is FieldStatus.REQUIRES_REVIEW
    assert result.value.parsed["range_low"] == "1"


def test_unknown_test_name_is_kept_not_merged():
    page = build_page([{"test": "HEMOGLOBIN A2", "value": "4.5", "unit": "%", "range": "2.1-3.5"}])
    result = one(page)
    assert result.test.raw == "HEMOGLOBIN A2"
    assert result.test.normalized == "hb_a2"      # exact vocabulary entry
    assert result.status is FieldStatus.VERIFIED


def test_similar_but_distinct_tests_are_not_merged():
    page = build_page(
        [
            {"test": "BILIRUBIN - TOTAL", "method": "PHOTOMETRY", "value": "0.58", "unit": "mg/dL", "range": "0.3-1.2"},
            {"test": "BILIRUBIN -DIRECT", "method": "PHOTOMETRY", "value": "0.13", "unit": "mg/dL", "range": "< 0.3"},
            {"test": "BILIRUBIN (INDIRECT)", "method": "CALCULATED", "value": "0.45", "unit": "mg/dL", "range": "0-0.9"},
        ]
    )
    document = run(page)
    assert [r.test.normalized for r in document.results] == [
        "bilirubin_total", "bilirubin_direct", "bilirubin_indirect"
    ]


def test_magnitude_outlier_flagged_not_changed():
    page = build_page(
        [{"test": "ALKALINE PHOSPHATASE", "value": "6563", "unit": "U/L", "range": "45-129"}]
    )
    result = one(page)
    assert result.value.raw == "6563"      # never modified
    assert result.value.status is FieldStatus.REQUIRES_REVIEW


def test_ocr_origin_is_never_auto_verified():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS"), (480.0, "Bio. Ref. Interval.")])
    builder.row([(26.0, "HEMOGLOBIN"), (240.0, "PHOTOMETRY"), (350.0, "9.2"), (420.0, "g/dL"), (480.0, "12.0-15.0")])
    page = builder.page()
    for line in page["lines"]:
        line["origin"] = "ocr"
        for word in line["words"]:
            word["confidence"] = 0.99
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    result = document.results[0]
    assert result.status is FieldStatus.REQUIRES_REVIEW
    assert result.value.evidence.origin == "ocr"
    assert any("OCR-derived" in reason for reason in result.value.reasons)


def test_duplicate_rows_are_collapsed():
    page = build_page(
        [
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
        ]
    )
    document = run(page)
    assert len(document.results) == 1


def test_conflicting_duplicates_are_flagged():
    page = build_page(
        [
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
            {"test": "HEMOGLOBIN", "value": "13.2", "unit": "g/dL", "range": "12.0-15.0"},
        ]
    )
    document = run(page)
    assert len(document.results) == 2
    assert all(r.status is FieldStatus.REQUIRES_REVIEW for r in document.results)


# --------------------------------------------------------------------------
# Report categories (synthetic)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows,expected_section",
    [
        ([{"test": "HEMOGLOBIN", "value": "13.5", "unit": "g/dL", "range": "12.0-15.0"}], "CBC / Hemogram"),
        ([{"test": "ALANINE TRANSAMINASE (SGPT)", "value": "22.53", "unit": "U/L", "range": "< 34"}], "Liver function"),
        ([{"test": "CREATININE - SERUM", "value": "0.52", "unit": "mg/dL", "range": "0.55-1.02"}], "Kidney function"),
        ([{"test": "SODIUM", "value": "136.17", "unit": "mmol/L", "range": "136-145"}], "Electrolytes"),
        ([{"test": "TOTAL CHOLESTEROL", "value": "113", "unit": "mg/dL", "range": "< 200"}], "Lipid profile"),
        ([{"test": "TSH - ULTRASENSITIVE", "value": "3.82", "unit": "µIU/mL", "range": "0.35-4.94"}], "Thyroid profile"),
        ([{"test": "TOTAL LEUCOCYTES COUNT (WBC)", "value": "6.02", "unit": "X 10³ / µL", "range": "4.0 - 10.0"}], "CBC / Hemogram"),
    ],
)
def test_sections_inferred(rows, expected_section):
    result = one(build_page(rows))
    assert result.section == expected_section


# --------------------------------------------------------------------------
# Malformed input
# --------------------------------------------------------------------------


def test_empty_page_produces_nothing():
    builder = PageBuilder()
    document = StructuredExtractionPipeline().process(DocBuilder().add(builder.page()).build())
    assert document.results == []


def test_header_without_rows():
    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    document = StructuredExtractionPipeline().process(DocBuilder().add(builder.page()).build())
    assert document.results == []


def test_page_with_only_garbage():
    builder = PageBuilder()
    builder.text("THIS PAGE INTENTIONALLY LEFT BLANK")
    document = StructuredExtractionPipeline().process(DocBuilder().add(builder.page()).build())
    assert document.results == []


def test_missing_lines_key_does_not_crash():
    payload = DocBuilder().add(PageBuilder().page()).build()
    payload["pages"][0].pop("lines")
    document = StructuredExtractionPipeline().process(payload)
    assert document.results == []


def test_result_document_serialises():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = run(page)
    data = document.to_dict()
    assert data["schema_version"] == "mediread.results/1"
    payload = json.dumps(data)
    assert "evidence" in payload and "status" in payload


# --------------------------------------------------------------------------
# Real corpus regression
# --------------------------------------------------------------------------

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts" / "extractions"


def _load(report_id: str):
    path = ARTIFACTS / f"{report_id}.extraction.json"
    if not path.exists():
        pytest.skip("corpus artefacts not generated in this environment")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "report_id,page,count",
    [
        ("4f16a4444054fdfe", 11, 24),   # hemogram
        ("4f16a4444054fdfe", 5, 12),    # liver function
        ("4f16a4444054fdfe", 3, 24),    # urine analysis
        ("c66749371af7e28c", 7, 10),    # lipid profile
        ("c66749371af7e28c", 10, 3),    # thyroid profile
    ],
)
def test_real_pages_result_counts(report_id, page, count):
    document = StructuredExtractionPipeline().process(_load(report_id))
    assert len([r for r in document.results if r.page == page]) == count


def test_real_hemogram_values_and_pq_unit():
    document = StructuredExtractionPipeline().process(_load("4f16a4444054fdfe"))
    by_test = {r.test.raw: r for r in document.results if r.page == 11}
    assert by_test["HEMOGLOBIN"].value.raw == "9.2"
    assert by_test["HEMOGLOBIN"].unit.raw == "g/dL"
    assert by_test["PLATELET COUNT"].value.raw == "264"
    mch = by_test["MEAN CORPUSCULAR HEMOGLOBIN(MCH)"]
    assert mch.unit.raw == "pq"
    assert mch.unit.status is FieldStatus.REQUIRES_REVIEW
    assert mch.unit.normalized is None


def test_real_urine_qualitative_rows():
    document = StructuredExtractionPipeline().process(_load("4f16a4444054fdfe"))
    by_test = {r.test.raw: r for r in document.results if r.page == 3}
    colour = by_test["COLOUR"]
    assert colour.value.raw == "PALE YELLOW"
    assert colour.status is FieldStatus.VERIFIED
    assert by_test["SPECIFIC GRAVITY"].value.status is FieldStatus.REQUIRES_REVIEW


def test_real_coagulation_range_from_continuation():
    document = StructuredExtractionPipeline().process(_load("4f16a4444054fdfe"))
    by_test = {r.test.raw: r for r in document.results if r.page == 4}
    assert by_test["PROTHROMBIN TIME"].reference.raw == "9.8-12.1 Seconds"
    assert by_test["INTERNATIONAL NORMALIZED RATIO"].reference.raw == "0.90-1.10"


def test_real_hplc_not_detected_rows():
    document = StructuredExtractionPipeline().process(_load("ac536c89c61f178c"))
    by_test = {r.test.raw: r for r in document.results}
    assert by_test["HEMOGLOBIN A2"].value.raw == "4.5"
    assert by_test["HEMOGLOBIN C"].value.normalized == "Not Detected"
    assert by_test["HEMOGLOBIN C"].unit.status is FieldStatus.MISSING


def test_real_headerless_page_is_flagged():
    document = StructuredExtractionPipeline().process(_load("79bd8cfc0570272b"))
    assert len(document.results) == 2
    assert all(r.status is FieldStatus.REQUIRES_REVIEW for r in document.results)
    assert {r.test.raw for r in document.results} == {"Hb A", "Hb A2"}
