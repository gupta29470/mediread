"""Assemble, validate, split and write the pilot SFT dataset."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from ..knowledge.store import KnowledgeStore
from . import templates as T
from .schema import EXAMPLE_SCHEMA_VERSION, validate_example

DATASET_VERSION = "mediread-sft-v0"
TARGET_SHARES = {
    "test_explanation": 0.35,
    "result_explanation": 0.20,
    "high_low": 0.15,
    "missing_information": 0.10,
    "qualitative": 0.05,
    "unsupported_test": 0.15,
    "follow_up": 0.05,
    "safety_refusal": 0.10,
    "adversarial": 0.05,
    "extraction_uncertainty": 0.05,
}
HIGH_RISK = ("safety_refusal", "adversarial", "unsupported_test")

_UNITS = {
    "CBC / Hemogram": "g/dL",
    "Vitamins": "ng/mL",
    "Iron studies": "µg/dL",
    "Inflammation markers": "mg/L",
    "Kidney function": "mg/dL",
    "Urine analysis": "mg/g",
}

_SYNTHETIC = {
    "inside": ("4.2", "2.0-5.0"),
    "below": ("1.1", "2.0-5.0"),
    "above": ("8.4", "2.0-5.0"),
}


def _family(example: dict) -> str:
    return example["knowledge_ids"][0] if example["knowledge_ids"] else example["provenance"]["template"]


def _split_for(family: str) -> str:
    bucket = int(hashlib.sha256(family.encode()).hexdigest()[:8], 16) % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "validation"
    return "test"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def _near_duplicate(a: str, b: str) -> bool:
    left, right = _tokens(a), _tokens(b)
    if not left or not right:
        return False
    return len(left & right) / len(left | right) > 0.92


def build_dataset(db_path: Path, *, limit: int | None = None) -> dict:
    store = KnowledgeStore.open(db_path)
    try:
        reviewed = [
            row["test_id"]
            for row in store._connection.execute(
                "SELECT test_id FROM tests WHERE review_status IN ('reviewed', 'approved') ORDER BY test_id"
            )
        ]
        raw: list[dict] = []
        for test_id in reviewed:
            entry = store.get(test_id)
            evidence = [row[0] for row in store._connection.execute(
                "SELECT evidence_id FROM evidence WHERE test_id = ? ORDER BY evidence_id", (test_id,)
            )]
            unit = _UNITS.get(entry["category"], "units")
            raw.extend(T.test_explanations(entry, evidence))
            for state in ("inside", "below", "above"):
                value, reference = _SYNTHETIC[state]
                raw.extend(T.result_explanations(
                    entry, evidence, value=value, unit=unit, reference=reference, state=state,
                ))
            high_value, reference = _SYNTHETIC["above"]
            low_value, _ = _SYNTHETIC["below"]
            raw.extend(T.high_low(entry, evidence, value=high_value, unit=unit, reference=reference, high=True))
            raw.extend(T.high_low(entry, evidence, value=low_value, unit=unit, reference=reference, high=False))
            raw.append(T.qualitative(entry["canonical_name"], "Negative"))
        raw.extend(T.missing_information("Haemoglobin"))
        raw.extend(T.unsupported(["Neopterin", "Procalcitonin", "Serum amyloid A"]))
        raw.append(T.ambiguous("Bilirubin"))
        raw.append(T.not_approved("Ferritin"))
        raw.append(T.follow_up())
        raw.extend(T.refusals())
        raw.extend(T.adversarial())
        raw.extend(T.uncertainty())
    finally:
        store.close()

    if limit:
        raw = raw[:limit]

    examples: list[dict] = []
    rejected: list[dict] = []
    duplicates = 0
    seen_outputs: set[tuple[str, str]] = set()
    for index, item in enumerate(raw, start=1):
        family = _family(item)
        example = {
            "example_id": f"ksft-{index:04d}",
            "schema_version": EXAMPLE_SCHEMA_VERSION,
            **item,
            "split": _split_for(family),
            "family": family,
            "validation": {"status": "pending", "findings": []},
        }
        check = validate_example(example)
        example["validation"] = {"status": "valid" if check.ok else "invalid", "findings": check.errors}
        if not check.ok:
            rejected.append({"example_id": example["example_id"], "category": example["category"],
                             "errors": check.errors})
            continue
        user_text = next((m["content"] for m in example["messages"] if m["role"] == "user"), "")
        key = (example["category"], " ".join(user_text.split()), " ".join(example["output"].split()))
        if key in seen_outputs:
            duplicates += 1
            continue
        seen_outputs.add(key)
        examples.append(example)

    # Near-duplicate detection inside a category (kept, but reported).
    near_dupes = []
    by_category: dict[str, list[dict]] = defaultdict(list)
    for example in examples:
        by_category[example["category"]].append(example)
    for category, items in by_category.items():
        for i, left in enumerate(items):
            for right in items[i + 1:]:
                if _near_duplicate(left["output"], right["output"]):
                    near_dupes.append([left["example_id"], right["example_id"]])

    families: dict[str, set[str]] = defaultdict(set)
    for example in examples:
        families[example["family"]].add(example["split"])
    leaked = {family: sorted(splits) for family, splits in families.items() if len(splits) > 1}

    report = {
        "dataset_version": DATASET_VERSION,
        "example_schema": EXAMPLE_SCHEMA_VERSION,
        "total": len(examples),
        "by_category": dict(sorted(Counter(e["category"] for e in examples).items())),
        "by_split": dict(sorted(Counter(e["split"] for e in examples).items())),
        "target_shares": TARGET_SHARES,
        "achieved_shares": {
            category: round(count / len(examples), 3)
            for category, count in sorted(Counter(e["category"] for e in examples).items())
        } if examples else {},
        "unique_families": len(families),
        "unique_tests": len({e["knowledge_ids"][0] for e in examples if e["knowledge_ids"]}),
        "unique_evidence": len({eid for e in examples for eid in e["evidence_ids"]}),
        "duplicates_removed": duplicates,
        "near_duplicates": near_dupes[:20],
        "near_duplicate_count": len(near_dupes),
        "invalid_examples": rejected,
        "invalid_count": len(rejected),
        "leakage": leaked,
        "leakage_count": len(leaked),
        "owner": "template generator, deterministic; no teacher model",
        "human_review_sample": [e["example_id"] for e in examples if e["category"] in HIGH_RISK][:12],
    }
    return {"examples": examples, "report": report}


def write_dataset(dataset: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    examples = dataset["examples"]
    counts = {}
    for split in ("train", "validation", "test"):
        rows = [example for example in examples if example["split"] == split]
        path = out_dir / f"{split}.jsonl"
        with path.open("w") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        counts[split] = len(rows)
    report = dict(dataset["report"], files={
        "train": str(out_dir / "train.jsonl"),
        "validation": str(out_dir / "validation.jsonl"),
        "test": str(out_dir / "test.jsonl"),
    }, split_counts=counts)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "dataset_card.md").write_text(_card(dataset, report))
    return report


def _card(dataset: dict, report: dict) -> str:
    lines = [
        f"# {DATASET_VERSION}",
        "",
        "Pilot instruction-tuning set for the on-device explanation model. Every example is",
        "generated deterministically by `mediread.training`; **no teacher model is used** and",
        "`provenance.teacher` is null for every row.",
        "",
        "| | |",
        "|---|---|",
        f"| examples | {report['total']} |",
        f"| schema | `{EXAMPLE_SCHEMA_VERSION}` |",
        f"| splits | {report['split_counts']} |",
        f"| unique tests | {report['unique_tests']} |",
        f"| unique evidence rows | {report['unique_evidence']} |",
        f"| invalid rejected | {report['invalid_count']} |",
        f"| duplicates removed | {report['duplicates_removed']} |",
        f"| near-duplicate pairs | {report['near_duplicate_count']} |",
        f"| family leakage | {report['leakage_count']} |",
        "",
        "## Category distribution",
        "",
        "| category | count | achieved share | target share |",
        "|---|---|---|---|",
    ]
    for category, count in report["by_category"].items():
        achieved = report["achieved_shares"].get(category, 0)
        target = TARGET_SHARES.get(category, 0)
        lines.append(f"| {category} | {count} | {achieved:.0%} | {target:.0%} |")
    lines += [
        "",
        "## Rules enforced by validation",
        "",
        "- the answer may only state numbers and ranges supplied in the prompt facts;",
        "- no diagnosis, treatment, medication change, urgency or invented citation;",
        "- the last chat message is the assistant answer and equals `output`;",
        "- categories, splits and provenance fields are from fixed vocabularies;",
        "- no PII-looking strings.",
        "",
        "## Splits",
        "",
        "Split by *family* (the knowledge test id, or the template family when there is no",
        "knowledge). A family is entirely in one split, so paraphrases of the same source",
        "cannot leak between train and test. The frozen 21-case benchmark in",
        "`src/mediread/llm_eval/` is not read by this pipeline and is not part of the set.",
        "",
        "## Known limits",
        "",
        "- Only tests with `reviewed`/`approved` knowledge produce knowledge-grounded",
        "  examples; the current package has 6 reviewed tests, so the knowledge-grounded",
        "  categories are small. The generator scales with review, not with synthetic volume.",
        "- Numeric values in `result_explanation` and `high_low` examples are synthetic",
        "  placeholders stated in the prompt; they are not reference intervals from the",
        "  knowledge package.",
        "",
        "## Human review",
        "",
        "High-risk categories (safety refusal, adversarial, unsupported) are listed in",
        "`report.json` under `human_review_sample`; review is pending.",
        "",
    ]
    return "\n".join(lines)
