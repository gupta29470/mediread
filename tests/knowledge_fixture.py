"""A small, self-contained knowledge package used by the knowledge tests.

It deliberately contains the cases the lookup contract must get right: an approved
test with aliases, two clinically distinct tests whose shared word is not an
alias, a draft entry that must not be permitted, and two tests that share an alias
(ambiguous).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from mediread.knowledge.builder import build_database
from mediread.knowledge.package import compute_content_hash, save_package
from mediread.knowledge.models import KnowledgePackage

SOURCE = {
    "source_id": "src_nlm",
    "title": "MedlinePlus: laboratory tests",
    "publisher": "MedlinePlus, U.S. National Library of Medicine",
    "source_url": "https://medlineplus.gov/lab-tests/",
    "publication_date": None,
    "access_date": "2026-11-07",
    "content_license": "public-domain (US federal government work)",
    "attribution_requirements": "Acknowledge 'Source: MedlinePlus, National Library of Medicine'.",
    "source_type": "government",
    "source_notes": None,
}


def _test(test_id: str, name: str, category: str, *, status: str, synonyms: list[str]) -> dict:
    return {
        "test_id": test_id,
        "canonical_name": name,
        "category": category,
        "what_it_measures": f"{name} is measured in blood to describe a physiological quantity.",
        "why_it_is_ordered": f"{name} may be ordered as part of a broader assessment.",
        "general_interpretation_high": f"A high {name} result is interpreted with the printed interval.",
        "general_interpretation_low": None,
        "limitations": [
            "The interval printed on the report is specific to the laboratory that produced it.",
        ],
        "related_test_ids": [],
        "review_status": status,
        "content_version": 1,
        "language": "en",
        "synonyms": synonyms,
    }


def _evidence(test_id: str) -> list[dict]:
    rows = []
    for claim in ("what_it_measures", "why_it_is_ordered", "general_interpretation_high", "limitations"):
        rows.append({
            "evidence_id": f"{test_id}__{claim}",
            "test_id": test_id,
            "source_id": "src_nlm",
            "claim_field": claim,
            "supporting_excerpt_or_reference": "MedlinePlus laboratory test page (accessed 2026-11-07).",
            "review_status": "approved",
        })
    return rows


TESTS = [
    _test("hemoglobin", "Hemoglobin", "CBC / Hemogram", status="approved",
          synonyms=["Haemoglobin", "Hb"]),
    _test("bilirubin_total", "Bilirubin, total", "Liver function", status="approved",
          synonyms=["Total bilirubin"]),
    _test("bilirubin_direct", "Bilirubin, direct", "Liver function", status="approved",
          synonyms=["Direct bilirubin"]),
    _test("cbc", "Complete blood count", "CBC / Hemogram", status="approved",
          synonyms=["CBC"]),
    _test("cbc_with_diff", "Complete blood count with differential", "CBC / Hemogram",
          status="draft", synonyms=["CBC panel"]),
]


def package_dict() -> dict:
    data = {
        "schema_version": "mediread.knowledge/1",
        "package": {
            "knowledge_version": "2026.11.1",
            "generated_at": "2026-11-09T00:00:00Z",
            "content_hash": "0" * 64,
            "notes": "test fixture",
            "default_language": "en",
        },
        "sources": [copy.deepcopy(SOURCE)],
        "tests": copy.deepcopy(TESTS),
        "aliases": [
            # The same alias on two tests must produce an ambiguous result.
            {"test_id": "cbc", "alias": "FBC", "alias_type": "synonym"},
            {"test_id": "cbc_with_diff", "alias": "FBC", "alias_type": "synonym"},
        ],
        "evidence": [row for test in TESTS for row in _evidence(test["test_id"])],
        "terminology": [],
    }
    data["package"]["content_hash"] = compute_content_hash(data)
    return data


def write_package(path: Path) -> Path:
    data = package_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return path


def build_fixture(tmp_path: Path) -> Path:
    """Validate + build the fixture; returns the SQLite path."""
    from mediread.knowledge.package import load_package

    package_path = write_package(tmp_path / "knowledge.json")
    package, _report = load_package(package_path)
    db_path = tmp_path / "knowledge.sqlite"
    build_database(package, db_path)
    return db_path
