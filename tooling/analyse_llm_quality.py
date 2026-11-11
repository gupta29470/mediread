#!/usr/bin/env python
"""Objective quality signals from saved outputs (complements the human rubric).

- value preservation: for a rewrite of a confirmed result, does the output keep
  the reported value verbatim?
- citation leakage: did the model inline a source id token like "[mp_lab_cbc]"?
- length: word count.

Usage: python tooling/analyse_llm_quality.py --run eval/llm/run1
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=str(ROOT / "eval" / "llm" / "run1"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "llm_eval" / "cases.json"))
    args = parser.parse_args()

    cases = {c["case_id"]: c for c in json.loads(Path(args.dataset).read_text())["cases"]}
    records = [json.loads(p.read_text()) for p in sorted(Path(args.run).glob("*/*.json"))
               if "checks" in json.loads(p.read_text())]
    rewrites = [r for r in records if r["task"] == "rewrite"]

    summary = {}
    for model in sorted({r["model"] for r in rewrites}):
        rows = [r for r in rewrites if r["model"] == model]
        checked = kept = leaks = 0
        words = []
        for record in rows:
            case = cases[record["case_id"]]
            text = (record["response"] or {}).get("rewritten_explanation") or ""
            words.append(len(text.split()))
            value = case["facts"].get("value_text")
            if value and case["facts"].get("value_confirmed"):
                checked += 1
                if value in text:
                    kept += 1
            if re.search(r"[\[(]mp_", text):
                leaks += 1
        summary[model] = {
            "rewrite_cases": len(rows),
            "value_kept": kept,
            "value_checked": checked,
            "value_preservation_rate": round(kept / checked, 4) if checked else None,
            "citation_leaks": leaks,
            "words_min": min(words),
            "words_median": sorted(words)[len(words) // 2],
            "words_max": max(words),
        }
        print(f"{model:14s} value {kept}/{checked} | leaks {leaks} | words "
              f"{min(words)}/{sorted(words)[len(words)//2]}/{max(words)}")

    out = Path(args.run) / "quality_signals.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
