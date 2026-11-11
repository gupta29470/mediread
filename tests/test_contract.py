"""Contract tests for ``mediread.results/1`` and the downstream interface.

These tests exercise **actual pipeline output** wherever possible, not only
hand-built schema objects. Real corpus artefacts are used when present; the suite
skips those cases otherwise so it still runs in a fresh checkout.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.structured import (
    SCHEMA_VERSION,
    ContractError,
    StructuredExtractionPipeline,
    build_explanation_input,
    load_document,
    load_results,
)
from mediread.structured.contract import (
    CONTRACT_VERSION,
    ExplanationInput,
    ResultView,
    parse_document,
    require_contract_version,
)
from mediread.structured.schema import ResultDocument
from tests.conftest import DocBuilder, build_page

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "extractions"
RESULTS = ROOT / "artifacts" / "results"
EXAMPLES = ROOT / "docs" / "examples"


def _has_corpus() -> bool:
    return (ARTIFACTS / "4f16a4444054fdfe.extraction.json").exists()


def _pipeline_document():
    payload = json.loads((ARTIFACTS / "4f16a4444054fdfe.extraction.json").read_text())
    return StructuredExtractionPipeline().process(payload, generated_at="2026-01-01T00:00:00+00:00")


needs_corpus = pytest.mark.skipif(not _has_corpus(), reason="corpus artefacts not generated")


# --------------------------------------------------------------------------
# Serialization round-trip
# --------------------------------------------------------------------------


@needs_corpus
def test_serialization_roundtrip_is_exact():
    document = _pipeline_document()
    payload = document.to_dict()
    restored = ResultDocument.from_dict(payload)
    again = restored.to_dict()
    assert json.loads(json.dumps(again)) == payload


@needs_corpus
def test_roundtrip_preserves_every_result_and_status():
    document = _pipeline_document()
    restored = ResultDocument.from_dict(document.to_dict())
    assert len(restored.results) == len(document.results)
    for original, copy in zip(document.results, restored.results):
        assert copy.result_id == original.result_id
        assert copy.status is original.status
        assert copy.value.raw == original.value.raw
        assert copy.unit.raw == original.unit.raw
        assert copy.reference.raw == original.reference.raw


def test_timestamp_is_serialized_and_restored():
    document = _pipeline_document()
    assert document.generated_at == "2026-01-01T00:00:00+00:00"
    restored = ResultDocument.from_dict(document.to_dict())
    assert restored.generated_at == document.generated_at


# --------------------------------------------------------------------------
# Schema version
# --------------------------------------------------------------------------


def test_schema_version_is_declared():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    assert document.to_dict()["schema_version"] == SCHEMA_VERSION


def test_unknown_schema_version_rejected():
    payload = {"schema_version": "mediread.results/999", "report_id": "x", "results": []}
    with pytest.raises(ContractError, match="unsupported schema_version"):
        parse_document(payload)


def test_missing_schema_version_rejected():
    with pytest.raises(ContractError, match="unsupported schema_version"):
        parse_document({"report_id": "x", "results": []})


def test_contract_version_guard():
    require_contract_version(CONTRACT_VERSION)
    with pytest.raises(ContractError):
        require_contract_version("mediread.explanation-input/0")


# --------------------------------------------------------------------------
# Missing / optional / unknown fields
# --------------------------------------------------------------------------


def _minimal_document() -> dict:
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    return document.to_dict()


def test_optional_document_fields_default():
    payload = _minimal_document()
    for key in ("warnings", "sections", "unparsed_rows", "engine_summary", "generated_at"):
        payload.pop(key, None)
    document = parse_document(payload, strict=True)
    assert document.warnings == []
    assert document.sections == []
    assert document.generated_at is None


def test_missing_required_field_is_rejected():
    payload = _minimal_document()
    payload["results"][0].pop("result_id")
    with pytest.raises(ContractError, match="result_id"):
        parse_document(payload)


def test_unknown_fields_are_ignored_for_forward_compatibility():
    payload = _minimal_document()
    payload["future_document_field"] = {"anything": 1}
    payload["results"][0]["future_result_field"] = "x"
    payload["results"][0]["value"]["future_field_field"] = [1, 2, 3]
    document = parse_document(payload, strict=True)
    assert len(document.results) == 1
    reserialized = document.to_dict()
    assert "future_document_field" not in reserialized
    assert reserialized["results"][0]["value"]["raw"] == "9.2"


# --------------------------------------------------------------------------
# Invalid values
# --------------------------------------------------------------------------


def test_invalid_field_status_rejected():
    payload = _minimal_document()
    payload["results"][0]["value"]["status"] = "probably-fine"
    with pytest.raises(ContractError, match="invalid status"):
        parse_document(payload)


def test_invalid_result_status_rejected():
    payload = _minimal_document()
    payload["results"][0]["status"] = "trusted"
    with pytest.raises(ContractError, match="invalid status"):
        parse_document(payload)


def test_inconsistent_declared_stats_rejected():
    payload = _minimal_document()
    payload["stats"]["results"] = payload["stats"].get("results", 1) + 5
    with pytest.raises(ContractError):
        parse_document(payload, strict=True)


def test_lenient_parse_allows_stale_stats():
    payload = _minimal_document()
    payload["stats"]["results"] = 999
    document = parse_document(payload, strict=False)
    assert len(document.results) == 1


# --------------------------------------------------------------------------
# Evidence, precision, original text
# --------------------------------------------------------------------------


@needs_corpus
def test_evidence_is_preserved_end_to_end():
    document = _pipeline_document()
    result = next(r for r in document.results if r.test.raw == "HEMOGLOBIN" and r.page == 11)
    evidence = result.value.evidence
    assert evidence is not None
    assert evidence.page == 11
    assert evidence.text == "9.2"
    assert evidence.bbox[2] > evidence.bbox[0]
    assert evidence.origin == "embedded"

    contract_input = build_explanation_input(document)
    view = next(r for r in contract_input if r.result_id == result.result_id)
    assert view.row_evidence is not None
    assert view.row_evidence.page == 11
    assert view.fields["value"].evidence.text == "9.2"


@needs_corpus
def test_decimal_precision_preserved():
    document = _pipeline_document()
    alp = next(r for r in document.results
               if r.test.raw == "ALKALINE PHOSPHATASE" and r.page == 5)
    assert alp.value.raw == "65.63"
    assert alp.value.normalized == "65.63"
    assert alp.value.parsed["precision"] == 2
    assert alp.reference.raw == "45-129"
    assert alp.reference.normalized == "45-129"


@needs_corpus
def test_original_text_never_overwritten():
    document = _pipeline_document()
    mch = next(r for r in document.results
               if r.test.raw == "MEAN CORPUSCULAR HEMOGLOBIN(MCH)")
    # The page prints "pq"; the vocabulary suspects "pg" but must not rewrite it.
    assert mch.unit.raw == "pq"
    assert mch.unit.normalized is None
    assert mch.unit.status.value == "requires_review"
    assert mch.unit.alternatives


@needs_corpus
def test_reference_precision_is_preserved():
    document = _pipeline_document()
    haem = next(r for r in document.results if r.test.raw == "HEMOGLOBIN" and r.page == 11)
    assert haem.reference.raw == "12.0-15.0"
    assert haem.reference.normalized == "12.0-15.0"
    assert haem.reference.parsed["low"] == 12.0


# --------------------------------------------------------------------------
# Stable identifiers and duplicates
# --------------------------------------------------------------------------


@needs_corpus
def test_result_ids_are_stable_across_runs():
    first = _pipeline_document()
    second = _pipeline_document()
    assert [r.result_id for r in first.results] == [r.result_id for r in second.results]
    assert len({r.result_id for r in first.results}) == len(first.results)


def test_duplicate_rows_reduce_counts_consistently():
    page = build_page(
        [
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
        ]
    )
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    assert len(document.results) == 1
    assert document.stats["results"] == 1
    assert sum(s.result_count for s in document.sections) == 1
    for name in ("test", "value", "unit", "reference"):
        assert sum(document.stats["field_statuses"][name].values()) == 1


def test_section_counts_match_results_after_duplicate_removal():
    """Regression: section counts were incremented before deduplication."""
    page = build_page(
        [
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
            {"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"},
            {"test": "TOTAL LEUCOCYTES COUNT (WBC)", "value": "6.02",
             "unit": "X 10³ / µL", "range": "4.0 - 10.0"},
        ]
    )
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    assert len(document.results) == 2
    assert sum(s.result_count for s in document.sections) == 2
    for section in document.sections:
        actual = sum(1 for r in document.results if r.section == section.name)
        assert section.result_count == actual


# --------------------------------------------------------------------------
# Corpus-wide contract compliance
# --------------------------------------------------------------------------


@pytest.mark.skipif(not RESULTS.exists(), reason="result artefacts not generated")
def test_every_artefact_loads_and_is_consistent():
    from mediread.structured.audit import audit_document

    paths = sorted(RESULTS.glob("*.results.json"))
    assert paths, "no result artefacts"
    for path in paths:
        document = load_document(path, strict=True)
        report = audit_document(document)
        assert report["consistent"], f"{path.name}: {report['problems']}"


@pytest.mark.skipif(not RESULTS.exists(), reason="result artefacts not generated")
def test_contract_projection_matches_document_counts():
    for path in sorted(RESULTS.glob("*.results.json")):
        document = load_document(path, strict=True)
        contract_input = build_explanation_input(document)
        assert len(contract_input) == len(document.results)
        assert isinstance(contract_input, ExplanationInput)
        for view in contract_input:
            assert isinstance(view, ResultView)
            assert view.report_id == document.report_id
            assert set(view.fields) >= {"test", "value", "unit", "reference"}


# --------------------------------------------------------------------------
# OCR source-trust policy through the contract
# --------------------------------------------------------------------------


def _ocr_page(**kwargs):
    page = build_page(
        [{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}]
    )
    for line in page["lines"]:
        line["origin"] = "ocr"
        for word in line["words"]:
            word["confidence"] = 0.98
    return page


def test_ocr_policy_survives_projection():
    document = StructuredExtractionPipeline().process(DocBuilder().add(_ocr_page()).build())
    view = build_explanation_input(document).results[0]
    assert view.status == "requires_review"
    assert view.fields["value"].status == "requires_review"
    assert view.fields["value"].evidence.origin == "ocr"
    assert any("OCR-derived" in reason for reason in view.fields["value"].reasons)
    assert view.needs_review is True


def test_embedded_result_can_be_verified():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    view = build_explanation_input(document).results[0]
    assert view.status == "verified"
    assert view.needs_review is False


# --------------------------------------------------------------------------
# Interface isolation
# --------------------------------------------------------------------------


def test_contract_module_does_not_import_ingestion():
    """The explanation engine must not depend on PDF/OCR internals."""
    import ast

    source = (ROOT / "src" / "mediread" / "structured" / "contract.py").read_text()
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(("." * node.level) + (node.module or ""))
    forbidden = [name for name in imported
                 if "ingest" in name or "pymupdf" in name or "ocr" in name or "fit" in name]
    assert not forbidden, f"contract imports extraction internals: {forbidden}"


def test_contract_input_has_no_extraction_internals():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    payload = build_explanation_input(document).to_dict()
    for forbidden in ("stats", "engine_summary", "unparsed_rows", "timings_ms", "page_class"):
        assert forbidden not in payload
        assert forbidden not in payload["results"][0]


def test_contract_serialization_is_deterministic():
    page = build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    document = StructuredExtractionPipeline().process(
        DocBuilder().add(page).build(), generated_at="2026-01-01T00:00:00+00:00"
    )
    first = build_explanation_input(document).to_json()
    second = build_explanation_input(document).to_json()
    assert first == second
    assert json.loads(first)["contract_version"] == CONTRACT_VERSION


# --------------------------------------------------------------------------
# Published examples must match the implementation
# --------------------------------------------------------------------------


@pytest.mark.skipif(not EXAMPLES.exists(), reason="examples not generated")
@pytest.mark.parametrize(
    "name,status,test_name",
    [
        ("verified_numeric", "verified", "HEMOGLOBIN"),
        ("missing_unit", "requires_review", "Hb A"),
        ("ocr_derived_review", "requires_review", "ALKALINE PHOSPHATASE"),
        ("qualitative", "verified", "COLOUR"),
        ("stratified_reference", "requires_review", "EST. GLOMERULAR FILTRATION RATE (eGFR)"),
    ],
)
def test_published_example_matches_contract(name, status, test_name):
    payload = json.loads((EXAMPLES / f"{name}.json").read_text())
    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["result"]["status"] == status
    assert payload["result"]["test_name"] == test_name
    assert payload["result"]["fields"]["value"]["text"] is not None


@pytest.mark.skipif(not EXAMPLES.exists(), reason="examples not generated")
def test_ocr_example_is_genuinely_ocr_derived():
    payload = json.loads((EXAMPLES / "ocr_derived_review.json").read_text())
    value = payload["result"]["fields"]["value"]
    assert value["evidence"]["origin"] == "ocr"
    assert value["evidence"]["confidence"] is not None
    assert any("OCR-derived" in reason for reason in value["reasons"])


@pytest.mark.skipif(not EXAMPLES.exists(), reason="examples not generated")
def test_stratified_example_has_no_asserted_bounds():
    payload = json.loads((EXAMPLES / "stratified_reference.json").read_text())
    field = payload["result"]["fields"]["reference"]
    assert field["status"] == "requires_review"
    bounds = payload["result"]["reference_bounds"]
    assert bounds is not None and bounds["stratified"] is True
    assert bounds["low"] is None and bounds["high"] is None
    assert field["text"]


# --------------------------------------------------------------------------
# Field-level usage gates (the consumer safety rule)
# --------------------------------------------------------------------------


def _project_one(page: dict):
    document = StructuredExtractionPipeline().process(DocBuilder().add(page).build())
    return build_explanation_input(document).results[0]


def test_verified_result_can_identify_and_interpret():
    view = _project_one(
        build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    )
    assert view.status == "verified"
    assert view.gates.identify_test.allowed
    assert view.gates.interpret_value.allowed
    assert view.gates.unit_comparison.allowed
    assert view.gates.range_comparison.allowed


def test_result_verified_does_not_imply_range_comparison():
    """The reviewer's case: a verified result with no reference range.

    A missing range does not downgrade the result (the value is still
    trustworthy), so result-level status is ``verified`` — yet comparing the
    value to a range must be blocked.
    """
    view = _project_one(build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL"}]))
    assert view.status == "verified"
    assert view.gates.interpret_value.allowed is True
    assert view.gates.range_comparison.allowed is False
    assert "reference" in view.gates.range_comparison.blocked_by


def test_gate_blocks_unit_comparison_on_ambiguous_unit():
    view = _project_one(
        build_page([{"test": "MEAN CORPUSCULAR HEMOGLOBIN(MCH)", "value": "21",
                     "unit": "pq", "range": "27.0-32.0"}])
    )
    assert view.gates.identify_test.allowed is True
    assert view.gates.interpret_value.allowed is True
    assert view.gates.unit_comparison.allowed is False
    assert "unit" in view.gates.unit_comparison.blocked_by
    # Range bounds are unit-dependent, so they are blocked as well.
    assert view.gates.range_comparison.allowed is False


def test_gate_blocks_range_on_stratified_reference():
    page = build_page(
        [{"test": "EST. GLOMERULAR FILTRATION RATE (eGFR)", "value": "112",
          "unit": "mL/min/1.73 m2"}],
        columns={"test": 26.0, "method": 240.0, "value": 350.0, "unit": 420.0},
    )
    # Turn the following row into a reference label and bands.
    from tests.conftest import PageBuilder

    builder = PageBuilder()
    builder.row([(26.0, "TEST NAME"), (240.0, "TECHNOLOGY"), (350.0, "VALUE"), (420.0, "UNITS")])
    builder.row([(26.0, "EST. GLOMERULAR FILTRATION RATE (eGFR)"), (240.0, "CALCULATED"),
                 (350.0, "112"), (420.0, "mL/min/1.73 m2")])
    builder.row([(26.0, "Bio. Ref. Interval. :-")])
    builder.row([(26.0, "> = 90 : Normal")])
    builder.row([(26.0, "60 - 89 : Mild Decrease")])
    document = StructuredExtractionPipeline().process(DocBuilder().add(builder.page()).build())
    view = build_explanation_input(document).results[0]
    assert view.gates.interpret_value.allowed is True
    assert view.gates.range_comparison.allowed is False
    assert "stratified" in view.gates.range_comparison.reason


def test_gate_allows_range_with_explicit_no_unit_marker():
    """Urine pH prints "-" as its unit; the printed marker is not missing data."""
    view = _project_one(
        build_page([{"test": "PH", "value": "5", "unit": "-", "range": "5-8"}],
                   columns={"test": 26.0, "value": 250.0, "unit": 380.0, "range": 450.0},
                   urinogram=True)
    )
    assert view.status == "verified"
    assert view.gates.unit_comparison.allowed is False   # no unit to compare
    assert view.gates.range_comparison.allowed is True   # interval is unit-free


def test_gate_blocks_bound_values():
    view = _project_one(
        build_page([{"test": "SPECIFIC GRAVITY", "value": "< 1.003", "unit": "-",
                     "range": "1.003-1.030"}],
                   columns={"test": 26.0, "value": 250.0, "unit": 380.0, "range": 450.0},
                   urinogram=True)
    )
    assert view.gates.interpret_value.allowed is False
    assert "value" in view.gates.interpret_value.blocked_by


def test_gate_blocks_every_purpose_for_ocr():
    view = _project_one(_ocr_page())
    assert view.gates.identify_test.allowed is False
    assert view.gates.interpret_value.allowed is False
    assert view.gates.unit_comparison.allowed is False
    assert view.gates.range_comparison.allowed is False
    assert "OCR" in (view.gates.identify_test.reason or "")


def test_gates_are_serialized():
    view = _project_one(
        build_page([{"test": "HEMOGLOBIN", "value": "9.2", "unit": "g/dL", "range": "12.0-15.0"}])
    )
    payload = view.to_dict()
    assert payload["gates"]["range_comparison"]["allowed"] is True
    assert set(payload["gates"]) == {
        "identify_test", "interpret_value", "unit_comparison", "range_comparison"
    }


@pytest.mark.skipif(not RESULTS.exists(), reason="result artefacts not generated")
def test_gates_are_never_allowed_on_unverified_fields():
    """Corpus-wide invariant: a gate implies its dependent fields are verified."""
    dependencies = {
        "identify_test": ("test",),
        "interpret_value": ("test", "value"),
        "unit_comparison": ("test", "value", "unit"),
        "range_comparison": ("test", "value", "reference"),
    }
    for path in sorted(RESULTS.glob("*.results.json")):
        for view in load_results(path):
            for gate_name, fields in dependencies.items():
                gate = getattr(view.gates, gate_name)
                if not gate.allowed:
                    continue
                for field_name in fields:
                    field = view.fields[field_name]
                    assert field.status == "verified", (
                        f"{view.result_id}: {gate_name} allowed but {field_name} is {field.status}"
                    )
                    assert field.evidence is None or field.evidence.origin != "ocr"
