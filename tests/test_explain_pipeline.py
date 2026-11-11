"""End-to-end explanation engine tests against real structured results."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from mediread.explain import ExplanationEngine
from mediread.explain.knowledge import CATALOGUE
from mediread.explain.models import ResultExplanationStatus, SectionKey
from mediread.structured.contract import load_results

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "artifacts" / "results"
SAMPLE = RESULTS / "4f16a4444054fdfe.results.json"
needs_corpus = pytest.mark.skipif(not SAMPLE.exists(), reason="result artefacts not generated")

SECTION_KEYS = {key.value for key in SectionKey}


def explain_sample():
    return ExplanationEngine().explain(
        load_results(SAMPLE), generated_at="2026-01-01T00:00:00+00:00"
    )


@needs_corpus
def test_every_result_has_all_six_sections():
    document = explain_sample()
    for result in document.results:
        assert {s.key.value for s in result.sections} == SECTION_KEYS


@needs_corpus
def test_permitted_sections_have_text_and_blocked_have_reasons():
    document = explain_sample()
    for result in document.results:
        for section in result.sections:
            if section.permitted:
                assert section.text, f"{result.test_name} {section.key} permitted but empty"
            else:
                assert section.reason, f"{result.test_name} {section.key} blocked without reason"


@needs_corpus
def test_schema_and_disclaimer():
    payload = explain_sample().to_dict()
    assert payload["schema_version"] == "mediread.explanation/1"
    assert payload["mode"] == "deterministic"
    assert payload["contract_version"] == "mediread.explanation-input/1"
    assert payload["knowledge_version"] == CATALOGUE.version
    assert "not a medical diagnosis" in payload["disclaimer"].lower()


@needs_corpus
def test_engine_is_deterministic():
    first = explain_sample().to_dict()
    second = explain_sample().to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@needs_corpus
def test_stats_denominators_add_up():
    document = explain_sample()
    stats = document.stats
    assert stats["results"] == len(document.results)
    assert sum(stats["by_status"].values()) == stats["results"]
    assert sum(stats["by_knowledge_status"].values()) == stats["results"]
    assert stats["fully_explained"] + stats["partially_explained"] + stats["withheld"] == stats["results"]


@needs_corpus
def test_education_sections_cite_resolvable_sources():
    document = explain_sample()
    for result in document.results:
        education = result.section(SectionKey.WHAT_THIS_TEST_MEASURES)
        if not education.permitted:
            continue
        assert education.sources, f"{result.test_name} education without a source"
        for source_id in education.sources:
            assert source_id in __import__(
                "mediread.explain.knowledge", fromlist=["SOURCES"]
            ).SOURCES
        sources_section = result.section(SectionKey.SOURCES)
        assert sources_section.permitted
        for source_id in education.sources:
            assert source_id in sources_section.sources


@pytest.mark.skipif(
    not (ROOT / "artifacts" / "extractions_ocr" / "ocr-example.extraction.json").exists(),
    reason="OCR extraction artefact not generated",
)
def test_ocr_results_never_get_education_or_comparison():
    from mediread.explain.knowledge import CATALOGUE as cat
    from mediread.structured import StructuredExtractionPipeline

    payload = json.loads(
        (ROOT / "artifacts" / "extractions_ocr" / "ocr-example.extraction.json").read_text()
    )
    results = StructuredExtractionPipeline().process(payload)
    from mediread.structured.contract import build_explanation_input

    document = ExplanationEngine().explain(build_explanation_input(results))
    assert document.results
    for result in document.results:
        assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False
        assert result.section(SectionKey.COMPARISON_WITH_REFERENCE).permitted is False
        reported = result.section(SectionKey.YOUR_REPORTED_RESULT).text
        assert "read from the report image by OCR" in reported


@needs_corpus
def test_unsupported_tests_never_get_education():
    document = explain_sample()
    for result in document.results:
        if result.knowledge_status == "unsupported":
            assert result.section(SectionKey.WHAT_THIS_TEST_MEASURES).permitted is False
            assert result.section(SectionKey.WHAT_THIS_MAY_GENERALLY_INDICATE).permitted is False


def test_knowledge_catalogue_is_valid():
    assert CATALOGUE.errors == ()
    assert len(CATALOGUE.entries()) >= 60
    for entry in CATALOGUE.entries():
        assert entry.sources
        assert entry.measures.strip()
        for source_id in entry.sources:
            source = __import__("mediread.explain.knowledge", fromlist=["SOURCES"]).SOURCES[source_id]
            assert source.url.startswith("https://")
            assert source.accessed


def test_engine_modules_do_not_import_extraction_internals():
    """The engine may import only the frozen contract."""
    explain_dir = ROOT / "src" / "mediread" / "explain"
    forbidden = ("pymupdf", "mediread.ingest", "mediread.ocr", "mediread.structured.pipeline",
                 "mediread.structured.schema")
    for path in explain_dir.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                level = "." * (node.level or 0)
                names = [level + node.module]
            for name in names:
                assert not any(fragment in name for fragment in forbidden), (
                    f"{path.name} imports {name}"
                )


@needs_corpus
def test_every_corpus_result_explains_without_error():
    engine = ExplanationEngine()
    count = 0
    for path in sorted(RESULTS.glob("*.results.json")):
        document = engine.explain(load_results(path))
        count += len(document.results)
    assert count == 325
