"""Phase 4 acceptance: dataset factory, validation, splits and leakage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mediread.training.factory import build_dataset, write_dataset
from mediread.training.schema import EXAMPLE_SCHEMA_VERSION, validate_example

REPO = Path(__file__).resolve().parents[1]
DATASET = REPO / "datasets" / "mediread-sft-v0"
DB = REPO / "artifacts" / "knowledge" / "mediread-knowledge.sqlite"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("dataset")
    dataset = build_dataset(DB)
    report = write_dataset(dataset, out)
    return dataset, report, out


def test_examples_are_valid_and_typed(built):
    dataset, _report, _out = built
    assert dataset["examples"]
    for example in dataset["examples"]:
        check = validate_example(example)
        assert check.ok, (example["example_id"], check.errors)
        assert example["schema_version"] == EXAMPLE_SCHEMA_VERSION
        assert example["provenance"]["teacher"] is None


def test_every_example_has_stable_id_and_assistant_turn(built):
    dataset, _report, _out = built
    ids = [example["example_id"] for example in dataset["examples"]]
    assert len(ids) == len(set(ids))
    for example in dataset["examples"]:
        assert example["messages"][-1]["role"] == "assistant"
        assert example["messages"][-1]["content"] == example["output"]


def test_families_do_not_leak_across_splits(built):
    dataset, report, _out = built
    assert report["leakage_count"] == 0
    families: dict[str, set[str]] = {}
    for example in dataset["examples"]:
        families.setdefault(example["family"], set()).add(example["split"])
    assert all(len(splits) == 1 for splits in families.values())
    assert set(report["split_counts"]) == {"train", "validation", "test"}


def test_knowledge_examples_cite_reviewed_knowledge(built):
    dataset, _report, _out = built
    grounded = [e for e in dataset["examples"] if e["knowledge_ids"]]
    assert grounded
    for example in grounded:
        assert example["evidence_ids"], example["example_id"]


def test_unsupported_examples_never_include_knowledge(built):
    dataset, _report, _out = built
    for example in dataset["examples"]:
        if example["category"] in ("unsupported_test", "safety_refusal", "adversarial"):
            assert not example["knowledge_ids"], example["example_id"]


def test_written_files_round_trip(built):
    _dataset, report, out = built
    total = 0
    for split in ("train", "validation", "test"):
        rows = [json.loads(line) for line in (out / f"{split}.jsonl").read_text().splitlines()]
        total += len(rows)
        for row in rows:
            assert row["split"] == split
            assert validate_example(row).ok
    assert total == report["total"]
    assert (out / "dataset_card.md").exists()
    assert (out / "report.json").exists()


def test_committed_dataset_matches_the_report():
    report = json.loads((DATASET / "report.json").read_text())
    assert report["total"] > 0
    assert report["invalid_count"] == 0
    assert report["leakage_count"] == 0
    assert report["unique_tests"] >= 1


def test_fabricated_number_is_rejected():
    example = {
        "example_id": "bad-1", "schema_version": EXAMPLE_SCHEMA_VERSION,
        "category": "result_explanation",
        "messages": [{"role": "user", "content": "q"},
                     {"role": "assistant", "content": "Your value is 9.9."}],
        "output": "Your value is 9.9.",
        "knowledge_ids": ["hemoglobin"], "evidence_ids": ["e"],
        "safety_behaviour": "explain_only", "permitted_numbers": ["4.2"],
        "split": "train", "provenance": {}, "validation": {},
    }
    check = validate_example(example)
    assert not check.ok
    assert any("unsupported number" in error for error in check.errors)


def test_diagnosis_assertion_is_rejected():
    example = {
        "example_id": "bad-2", "schema_version": EXAMPLE_SCHEMA_VERSION,
        "category": "safety_refusal",
        "messages": [{"role": "user", "content": "Do I have gout?"},
                     {"role": "assistant", "content": "Yes, you have gout and should take allopurinol."}],
        "output": "Yes, you have gout and should take allopurinol.",
        "knowledge_ids": [], "evidence_ids": [], "safety_behaviour": "refuse_diagnosis",
        "permitted_numbers": [], "split": "train", "provenance": {}, "validation": {},
    }
    check = validate_example(example)
    assert not check.ok
    assert any("diagnosis" in error for error in check.errors)


def test_negated_refusal_is_allowed():
    example = {
        "example_id": "ok-1", "schema_version": EXAMPLE_SCHEMA_VERSION,
        "category": "safety_refusal",
        "messages": [{"role": "user", "content": "Do I have gout?"},
                     {"role": "assistant", "content": "MediRead does not diagnose conditions."}],
        "output": "MediRead does not diagnose conditions.",
        "knowledge_ids": [], "evidence_ids": [], "safety_behaviour": "refuse_diagnosis",
        "permitted_numbers": [], "split": "train", "provenance": {}, "validation": {},
    }
    assert validate_example(example).ok
