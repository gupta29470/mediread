#!/usr/bin/env python
"""Run the on-device LLM evaluation against local Ollama.

Usage:
    python tooling/run_llm_eval.py                    # all three models, all cases
    python tooling/run_llm_eval.py --models qwen3.5:4b
    python tooling/run_llm_eval.py --cases R03_below_range F01_anemia_question
    python tooling/run_llm_eval.py --out eval/llm/smoke --repeat 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.llm_eval.dataset import load_dataset  # noqa: E402
from mediread.llm_eval.runner import MODELS, run_all  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "data" / "llm_eval" / "cases.json"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "llm" / "run"))
    parser.add_argument("--models", nargs="*", default=list(MODELS))
    parser.add_argument("--cases", nargs="*", default=None)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    if args.cases:
        wanted = set(args.cases)
        dataset.cases = [case for case in dataset.cases if case.case_id in wanted]
        missing = wanted - {case.case_id for case in dataset.cases}
        if missing:
            print(f"unknown case ids: {sorted(missing)}", file=sys.stderr)
            return 2

    print(f"{len(dataset.cases)} cases x {len(args.models)} models -> {args.out}")
    result = run_all(dataset, Path(args.out), models=args.models, repeat=args.repeat)
    print("\n=== summary")
    for summary in result["models"]:
        print(f"{summary['model']:14s} schema={summary['schema_valid_rate']} "
              f"pass={summary['pass_rate']} "
              f"num_viol={summary['number_violations']} "
              f"safety_viol={summary['safety_violations']} "
              f"perm_viol={summary['permission_violations']} "
              f"answerable_acc={summary['answerable_accuracy']} "
              f"median={summary['latency_ms_median']}ms "
              f"tok/s={summary['tokens_per_second_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
