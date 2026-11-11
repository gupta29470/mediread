#!/usr/bin/env python
"""Re-evaluate saved model responses with the current checker.

Model outputs are immutable; only the checks are recomputed. This exists because
three checker defects were found after the sweep (negation scope, permission
phrasing, and an over-strict expectation for unconfirmed text). Re-running the
models would not test anything new.

Usage: python tooling/recheck_llm_eval.py --run eval/llm/run1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.llm_eval.checks import evaluate  # noqa: E402
from mediread.llm_eval.dataset import load_dataset  # noqa: E402
from mediread.llm_eval.metrics import aggregate, per_case_matrix  # noqa: E402
from mediread.llm_eval.schema import SchemaError, parse_json, validate_response  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="eval/llm/run1")
    parser.add_argument("--dataset", default="data/llm_eval/cases.json")
    args = parser.parse_args()

    run_dir = Path(args.run)
    dataset = load_dataset(args.dataset)
    cases = {case.case_id: case for case in dataset.cases}
    changed = 0

    for path in sorted(run_dir.glob("*/*.json")):
        record = json.loads(path.read_text())
        if "checks" not in record:
            continue
        case = cases.get(record["case_id"])
        if case is None:
            print(f"skipping unknown case {record['case_id']}")
            continue
        payload, schema_valid, schema_error = None, False, None
        try:
            payload = validate_response(case.task, parse_json(record["response_raw"]))
            schema_valid = True
        except SchemaError as exc:
            schema_error = str(exc)
        old = record["checks"]
        record["checks"] = evaluate(case, payload or {}, schema_valid=schema_valid).to_dict()
        record["schema_error"] = schema_error
        record["response"] = payload
        if old["passed"] != record["checks"]["passed"] or old["violations"] != record["checks"]["violations"]:
            changed += 1
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    manifest = json.loads((run_dir / "manifest.json").read_text())
    records = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*/*.json"))
               if "checks" in json.loads(p.read_text())]
    summary = aggregate(records, manifest)
    (run_dir / "summary.json").write_text(
        json.dumps({"manifest": manifest, "models": list(summary["models"].values())}, indent=2),
        encoding="utf-8",
    )
    print(f"rechecked {len(records)} records, {changed} changed verdict")
    for model, row in summary["models"].items():
        print(f"{model:14s} pass={row['pass_rate']:.3f} num={row['number_violations']} "
              f"safety={row['safety_violations']} perm={row['permission_violations']} "
              f"answerable={row['answerable_accuracy']} refusals={row['correct_refusals']}/"
              f"{row['unanswerable_cases']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
