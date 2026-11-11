#!/usr/bin/env python
"""Generate and print educational explanations for a structured result file.

Usage:
    python tooling/explain_report.py artifacts/results/<id>.results.json
    python tooling/explain_report.py artifacts/results --out artifacts/explanations
    python tooling/explain_report.py <file> --only HEMOGLOBIN --json

Output is local only; it contains laboratory content.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.explain import ExplanationEngine  # noqa: E402
from mediread.explain.serialization import write_explanations  # noqa: E402
from mediread.structured.contract import load_results  # noqa: E402


def print_result(result, show_blocked: bool) -> None:
    print(f"\n{'=' * 78}\n{result.test_name}  [{result.status.value}]  "
          f"knowledge={result.knowledge_status}")
    for section in result.sections:
        if not section.permitted:
            if show_blocked:
                print(f"  -- {section.key.value}: BLOCKED ({section.reason})")
            continue
        print(f"  [{section.key.value}]")
        print(f"    {section.text}")
        if section.sources:
            print(f"    sources: {', '.join(section.sources)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="results JSON or directory")
    parser.add_argument("--out", help="write explanation JSON here")
    parser.add_argument("--only", help="filter by test name substring")
    parser.add_argument("--json", action="store_true", help="print JSON instead of prose")
    parser.add_argument("--show-blocked", action="store_true", help="print blocked sections")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    target = Path(args.target)
    files = sorted(target.glob("*.results.json")) if target.is_dir() else [target]
    engine = ExplanationEngine()

    for path in files:
        document = engine.explain(load_results(path))
        if args.out:
            saved = write_explanations(document, args.out)
            print(f"{path.name}: {len(document.results)} results -> {saved}")
        if args.json:
            payload = document.to_dict()
            if args.only:
                payload["results"] = [
                    r for r in payload["results"] if args.only.lower() in r["test_name"].lower()
                ]
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            continue
        print(f"\n### {document.report_id} — {document.source_filename}")
        print(f"    knowledge {document.knowledge_version} | stats {document.stats['by_status']}")
        shown = 0
        for result in document.results:
            if args.only and args.only.lower() not in result.test_name.lower():
                continue
            print_result(result, args.show_blocked)
            shown += 1
            if args.limit and shown >= args.limit:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
