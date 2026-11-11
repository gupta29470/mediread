#!/usr/bin/env python
"""Reproducible corpus statistics for the structured-result contract.

The evaluation report used to quote corpus numbers that were transcribed by hand.
They drifted: one report showed 326 results while the artefacts contained 325,
because a stale snapshot predated a parser fix. This tool exists so the numbers
are regenerated from the committed artefacts and every count is checked.

It validates each serialized document against the contract (deserialization with
``strict=True``), runs the counting invariants, and prints the aggregate.

Usage:
    python tooling/audit_results.py
    python tooling/audit_results.py --out eval/results_audit.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, EVAL_DIR  # noqa: E402
from mediread.structured.audit import audit_document  # noqa: E402
from mediread.structured.contract import load_document  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default=str(ARTIFACTS_DIR / "results"))
    parser.add_argument("--out", default=str(EVAL_DIR / "results_audit.json"))
    args = parser.parse_args()

    directory = Path(args.results)
    paths = sorted(directory.glob("*.results.json"))
    if not paths:
        raise SystemExit(f"no result artefacts in {directory}")

    result_status: Counter = Counter()
    field_status: dict[str, Counter] = {n: Counter() for n in ("test", "value", "unit", "reference")}
    sections: Counter = Counter()
    per_report = []
    total_results = 0
    total_unparsed = 0
    problems: list[str] = []

    for path in paths:
        document = load_document(path, strict=True)
        report = audit_document(document)
        if not report["consistent"]:
            problems.extend(f"{path.name}: {p}" for p in report["problems"])

        total_results += len(document.results)
        total_unparsed += len(document.unparsed_rows)
        for result in document.results:
            result_status[result.status.value] += 1
            for name in field_status:
                field_status[name][getattr(result, name).status.value] += 1
        for section in document.sections:
            sections[section.name] += section.result_count

        per_report.append(
            {
                "report_id": document.report_id,
                "results": len(document.results),
                "verified": sum(1 for r in document.results if r.status.value == "verified"),
                "review": sum(
                    1 for r in document.results
                    if r.status.value in ("requires_review", "uncertain")
                ),
                "unparsed_rows": len(document.unparsed_rows),
                "pages_with_results": document.pages_with_results,
                "consistent": report["consistent"],
            }
        )

    # Invariants that must hold across the corpus.
    for name, counter in field_status.items():
        if sum(counter.values()) != total_results:
            problems.append(
                f"{name} field total {sum(counter.values())} != result total {total_results}"
            )
    if sum(sections.values()) != total_results:
        problems.append(f"section total {sum(sections.values())} != result total {total_results}")

    review = result_status.get("requires_review", 0) + result_status.get("uncertain", 0)
    summary = {
        "reports": len(paths),
        "results": total_results,
        "results_by_status": dict(result_status),
        "review_rate": round(review / total_results, 4) if total_results else 0.0,
        "field_status": {name: dict(counter) for name, counter in field_status.items()},
        "field_totals": {name: sum(counter.values()) for name, counter in field_status.items()},
        "sections": dict(sections.most_common()),
        "unparsed_rows": total_unparsed,
        "per_report": per_report,
        "problems": problems,
        "consistent": not problems,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"reports={len(paths)} results={total_results} review_rate={summary['review_rate']:.4f}")
    print("results by status:", dict(result_status))
    for name, counter in field_status.items():
        print(f"  {name:10s} total={sum(counter.values()):>3} {dict(counter)}")
    print(f"sections total={sum(sections.values())}")
    print(f"unparsed rows={total_unparsed}")
    print("consistency:", "OK" if summary["consistent"] else summary["problems"])
    print(f"-> {out}")
    return 0 if summary["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
