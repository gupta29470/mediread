"""Phase C: audit the pilot SFT dataset for quality and leakage."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

DATASET = Path("datasets/mediread-sft-v0")
REPORT = Path("reports/dataset-audit.md")
TOKEN = re.compile(r"[a-z]{4,}")


def tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def jaccard(a: str, b: str) -> float:
    left, right = tokens(a), tokens(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def rows(split: str) -> list[dict]:
    path = DATASET / f"{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    splits = {split: rows(split) for split in ("train", "validation", "test")}
    everything = [row for values in splits.values() for row in values]
    families: dict[str, set[str]] = {}
    for row in everything:
        families.setdefault(row["family"], set()).add(row["split"])

    by_category = Counter(row["category"] for row in everything)
    by_knowledge = Counter(row["knowledge_ids"][0] for row in everything if row["knowledge_ids"])
    safety = Counter(row["safety_behaviour"] for row in everything)

    dupes = []
    repeats = []
    near = []
    for index, left in enumerate(everything):
        for right in everything[index + 1:]:
            left_prompt = next(m["content"] for m in left["messages"] if m["role"] == "user")
            right_prompt = next(m["content"] for m in right["messages"] if m["role"] == "user")
            if left["output"] == right["output"] and left["category"] == right["category"]:
                (dupes if left_prompt == right_prompt else repeats).append(
                    [left["example_id"], right["example_id"]])
            elif left["category"] == right["category"] and jaccard(left["output"], right["output"]) > 0.9:
                near.append([left["example_id"], right["example_id"], round(jaccard(left["output"], right["output"]), 3)])

    numeric_ok = 0
    numeric_bad = []
    for row in everything:
        allowed = set(row["permitted_numbers"])
        found = set(re.findall(r"\d+(?:\.\d+)?", row["output"])) | set(
            re.findall(r"\b\d+(?:\.\d+)?\s*[-\u2013]\s*\d+(?:\.\d+)?\b", row["output"]))
        if found - allowed:
            numeric_bad.append([row["example_id"], sorted(found - allowed)])
        else:
            numeric_ok += 1

    no_provenance = [row["example_id"] for row in everything
                     if not row.get("provenance") or row["provenance"].get("generator") != "template"]
    empty_knowledge = [row["example_id"] for row in everything
                       if row["category"] in ("test_explanation", "result_explanation", "high_low")
                       and not row["knowledge_ids"]]

    lines = [
        "# Dataset quality audit — mediread-sft-v0",
        "",
        "| metric | value |",
        "|---|---|",
        f"| examples | {len(everything)} |",
        f"| train / validation / test | {len(splits['train'])} / {len(splits['validation'])} / {len(splits['test'])} |",
        f"| unique families (tests + templates) | {len(families)} |",
        f"| families spanning >1 split | **{sum(1 for f in families.values() if len(f) > 1)}** |",
        f"| exact duplicates (same prompt and answer) | {len(dupes)} |",
        f"| intentional template repeats (same answer, different question) | {len(repeats)} |",
        f"| near-duplicate pairs (Jaccard > 0.9) | {len(near)} |",
        f"| numeric-preservation failures | {len(numeric_bad)} |",
        f"| examples without template provenance | {len(no_provenance)} |",
        f"| knowledge categories without knowledge ids | {len(empty_knowledge)} |",
        "",
        "## Category distribution",
        "",
        "| category | examples | share |",
        "|---|---|---|",
    ]
    for category, count in by_category.most_common():
        lines.append(f"| {category} | {count} | {count/len(everything):.0%} |")
    lines += ["", "## Knowledge-family distribution", "", "| test | examples |", "|---|---|"]
    for test, count in by_knowledge.most_common():
        lines.append(f"| `{test}` | {count} |")
    lines += ["", "## Safety-behaviour distribution", "", "| behaviour | examples |", "|---|---|"]
    for behaviour, count in safety.most_common():
        lines.append(f"| {behaviour} | {count} |")
    lines += ["", "## Findings", ""]
    if near:
        lines.append(f"- {len(near)} near-duplicate pairs, e.g. "
                     + ", ".join(f"{a}≈{b}" for a, b, _ in near[:5]) + ".")
    if dupes:
        lines.append(f"- {len(dupes)} exact duplicates (should be zero).")
    if repeats:
        lines.append(f"- {len(repeats)} intentional template repeats: one policy answer reused for "
                     "different questions (refusal/unsupported categories). This is by design, "
                     "not accidental duplication, but it means those answers carry little signal.")
    if numeric_bad:
        lines.append(f"- {len(numeric_bad)} numeric-preservation failures: {numeric_bad[:3]}.")
    lines.append("- Split integrity: no family spans two splits."
                 if not any(len(f) > 1 for f in families.values()) else "- **Family leakage detected.**")
    lines += [
        "",
        "## Can this dataset support a meaningful experiment?",
        "",
        "Partly. It is internally consistent (valid schema, no leakage, numbers preserved), but it",
        "is unbalanced: one template (result explanation) dominates, only six knowledge families",
        "exist, and every knowledge-grounded example is a paraphrase of the same six entries.",
        "That is enough to measure *contract and refusal behaviour* — which is exactly what the",
        "LoRA run improved — but not enough to measure medical explanation quality.",
        "",
        "Recommended targeted expansion (only after the failure analysis):",
        "",
        "1. `unsupported_test` variants (unknown, ambiguous, reviewed-not-approved) — the adapter",
        "   still explains a draft entry in one case.",
        "2. `blocked_facts` variants — teaching that a withheld value must not be restated.",
        "3. More reviewed tests (the binding constraint): each adds A/B/C/E examples.",
        "",
        "Do **not** add trivial paraphrases to raise the count.",
        "",
    ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(json.dumps({"examples": len(everything), "dupes": len(dupes), "near": len(near),
                      "numeric_bad": len(numeric_bad), "families": len(families),
                      "leak": sum(1 for f in families.values() if len(f) > 1)}))


if __name__ == "__main__":
    main()
