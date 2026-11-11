"""Semantic validation, status transitions and the review log."""

from __future__ import annotations

import json

import pytest

from mediread.knowledge import cli
from mediread.knowledge.package import KnowledgePackageError, load_package
from mediread.knowledge.validate import validate_package

from tests.knowledge_fixture import package_dict


def errors_for(mutate) -> list[str]:
    data = package_dict()
    mutate(data)
    return validate_package(data).errors


def warnings_for(mutate) -> list[str]:
    data = package_dict()
    mutate(data)
    return validate_package(data).warnings


def test_valid_fixture_has_no_errors():
    report = validate_package(package_dict())
    assert report.errors == []
    assert report.stats["tests"] == 5
    assert report.stats["by_status"]["approved"] == 4


def test_duplicate_test_id_is_an_error():
    def mutate(data):
        data["tests"].append(dict(data["tests"][0]))
    assert any("duplicate test_id" in e for e in errors_for(mutate))


def test_broken_related_test_reference_is_an_error():
    def mutate(data):
        data["tests"][0]["related_test_ids"] = ["does_not_exist"]
    assert any("does_not_exist" in e for e in errors_for(mutate))


def test_duplicate_alias_on_one_test_is_an_error():
    def mutate(data):
        data["tests"][0]["synonyms"] = ["Haemoglobin", "Haemoglobin"]
    assert any("duplicate alias" in e for e in errors_for(mutate))


def test_missing_evidence_for_a_claim_is_an_error():
    def mutate(data):
        data["evidence"] = [row for row in data["evidence"]
                            if not (row["test_id"] == "hemoglobin" and row["claim_field"] == "why_it_is_ordered")]
    assert any("no evidence for why_it_is_ordered" in e for e in errors_for(mutate))


def test_evidence_for_missing_source_is_an_error():
    def mutate(data):
        data["evidence"][0]["source_id"] = "ghost_source"
    assert any("ghost_source" in e for e in errors_for(mutate))


def test_generic_range_in_interpretation_is_an_error():
    def mutate(data):
        data["tests"][0]["general_interpretation_high"] = "A result above 13.0 - 17.0 is usually considered high."
    assert any("must not carry reference intervals" in e for e in errors_for(mutate))


def test_range_in_measures_is_a_warning_not_an_error():
    data = package_dict()
    data["tests"][0]["what_it_measures"] = "Measured in blood; typical values are 13 - 17 units."
    report = validate_package(data)
    assert not [e for e in report.errors if "numeric range" in e]
    assert any("mentions a numeric range" in w for w in report.warnings)


def test_source_without_licence_is_an_error():
    def mutate(data):
        data["sources"][0]["content_license"] = ""
    assert any("missing content_license" in e for e in errors_for(mutate))


def test_shared_alias_is_reported_as_ambiguous():
    data = package_dict()
    data["aliases"] = [{"test_id": "hemoglobin", "alias": "FBC"},
                       {"test_id": "cbc", "alias": "FBC"}]
    report = validate_package(data)
    assert report.stats["ambiguous_aliases"].get("fbc") == ["cbc", "hemoglobin"]
    assert any("ambiguous alias" in w for w in report.warnings)


def test_invalid_review_status_is_an_error():
    data = package_dict()
    data["tests"][0]["review_status"] = "published"
    report = validate_package(data)
    assert any("invalid review_status" in e for e in report.errors)


def test_illegal_transition_is_rejected_by_the_cli(tmp_path, capsys):
    package_path = tmp_path / "knowledge.json"
    package_path.write_text(json.dumps(package_dict()))
    # draft -> approved must not be allowed: review happens first.
    package_path = tmp_path / "knowledge.json"
    code = cli.main([
        "set-status", "--package", str(package_path), "--test-id", "cbc_with_diff",
        "--status", "approved", "--reviewer", "Reviewer", "--note", "skip review",
    ])
    assert code == 1
    assert "illegal transition" in capsys.readouterr().err


def test_legal_transition_is_recorded(tmp_path, capsys):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(package_dict()))
    code = cli.main([
        "set-status", "--package", str(path), "--test-id", "cbc_with_diff",
        "--status", "reviewed", "--reviewer", "Dr Reviewer (chemical pathology)",
        "--note", "checked claims against the source",
    ])
    assert code == 0
    package, _ = load_package(path)
    assert package.tests_by_id["cbc_with_diff"].review_status == "reviewed"
    assert package.tests_by_id["cbc_with_diff"].content_version == 2
    log = (tmp_path / "review_log.jsonl").read_text().strip().splitlines()
    entry = json.loads(log[-1])
    assert entry["to_status"] == "reviewed"
    assert entry["reviewer"].startswith("Dr Reviewer")
    assert entry["package_content_hash"] == package.content_hash


def test_corpus_report_counts_and_coverage(tmp_path, capsys):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(package_dict()))
    code = cli.main(["report", "--package", str(path)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stats"]["tests"] == 5
    assert out["stats"]["by_status"] == {"draft": 1, "reviewed": 0, "approved": 4}
    assert out["stats"]["sources"] == 1
    assert out["stats"]["tests_with_high_note"] == 5
    assert out["stats"]["ambiguous_aliases"]["fbc"] == ["cbc", "cbc_with_diff"]
