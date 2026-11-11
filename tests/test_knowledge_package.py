"""Package loading, schema validation, versioning and the migrated corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.knowledge.builder import build_database, read_metadata
from mediread.knowledge.models import KnowledgePackage, normalise_name
from mediread.knowledge.package import (
    KnowledgePackageError,
    compute_content_hash,
    load_package,
    save_package,
    schema_errors,
)
from mediread.knowledge.validate import validate_package

from .knowledge_fixture import package_dict, write_package

REPO = Path(__file__).resolve().parents[1]
KNOWLEDGE_JSON = REPO / "knowledge" / "mediread-knowledge.json"


def test_fixture_package_validates_and_hashes(tmp_path):
    path = write_package(tmp_path / "k.json")
    package, report = load_package(path)
    assert report.ok
    assert package.content_hash == compute_content_hash(package.to_json())
    assert len(package.tests) == 5
    assert len(package.all_aliases()) > len(package.tests)


def test_schema_rejects_missing_required_field(tmp_path):
    data = package_dict()
    del data["tests"][0]["limitations"]
    assert any("limitations" in error for error in schema_errors(data))


def test_schema_rejects_unknown_field(tmp_path):
    data = package_dict()
    data["tests"][0]["reference_range"] = "4.0-10.0"
    assert any("reference_range" in error and "Additional properties" in error
               for error in schema_errors(data))


def test_tampered_content_hash_is_rejected(tmp_path):
    data = package_dict()
    data["tests"][0]["what_it_measures"] = "A different claim that was not in the reviewed content."
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(data))
    with pytest.raises(KnowledgePackageError) as error:
        load_package(path)
    assert "content_hash" in str(error.value)


def test_save_refreshes_hash_and_round_trips(tmp_path):
    path = write_package(tmp_path / "k.json")
    package, _ = load_package(path)
    package.notes = "edited"
    refreshed = save_package(package, path)
    again, _ = load_package(path)
    assert again.content_hash == refreshed
    assert again.notes == "edited"


def test_build_writes_metadata_and_counts(tmp_path):
    path = write_package(tmp_path / "k.json")
    package, _ = load_package(path)
    db = tmp_path / "k.sqlite"
    manifest = build_database(package, db)
    metadata = read_metadata(db)
    assert metadata["schema_version"] == "mediread.knowledge/1"
    assert metadata["db_schema_version"] == "1"
    assert metadata["knowledge_version"] == "2026.11.1"
    assert metadata["content_hash"] == package.content_hash
    assert int(metadata["test_count"]) == len(package.tests)
    assert int(metadata["approved_count"]) == 4
    assert manifest["sha256"] and manifest["bytes"] > 0
    assert db.with_suffix(".sqlite.manifest.json").exists()


def test_migrated_corpus_is_valid_and_never_claims_approval():
    """The committed package must load, validate and be honest about review state."""
    assert KNOWLEDGE_JSON.exists(), "run: python -m mediread.knowledge.cli migrate-legacy"
    package, report = load_package(KNOWLEDGE_JSON)
    assert report.ok
    assert len(package.tests) >= 30
    assert len(package.sources) >= 5
    statuses = package.status_counts()
    assert statuses["approved"] == 0, "no entry may be marked approved without independent review"
    # Reviewed entries came from the engineering claim audit only; clinical sign-off
    # is still pending, so approved must stay at zero.
    assert statuses["reviewed"] + statuses["draft"] == len(package.tests)
    # Every substantive claim has an evidence row.
    for test in package.tests:
        claims = {item.claim_field for item in package.evidence_for(test.test_id)}
        assert {"what_it_measures", "why_it_is_ordered"} <= claims
    # Licensing metadata is present on every source.
    for source in package.sources:
        assert source.content_license
        assert source.attribution_requirements
    # No generic reference intervals in the general-interpretation fields.
    report = validate_package(package.to_json())
    assert not [error for error in report.errors if "numeric range" in error]


def test_normaliser_matches_legacy_rules():
    assert normalise_name("HbA1c") == "hba1c"
    assert normalise_name("  Vitamin   B-12 ") == "vitamin b 12"
    assert normalise_name("µg/mL") == "ug ml"
