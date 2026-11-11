#!/usr/bin/env python
"""Aggregate the four-model benchmark into a comparison table."""

from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "llm" / "bench"
CASES = {c["case_id"]: c for c in json.loads((ROOT / "data" / "llm_eval" / "cases.json").read_text())["cases"]}


def load_records() -> list[dict]:
    records = []
    for path in sorted(glob.glob(str(BENCH / "*" / "*" / "*.json"))):
        try:
            record = json.loads(Path(path).read_text())
        except json.JSONDecodeError:
            continue
        if "checks" in record:
            record["_path"] = path
            records.append(record)
    return records


def summarise(records: list[dict]) -> dict:
    total = len(records)
    schema = sum(1 for r in records if r["checks"]["schema_valid"])
    passed = sum(1 for r in records if r["checks"]["passed"])
    followups = [r for r in records if r["task"] == "followup"]
    answerable_ok = sum(
        1 for r in followups
        if r["checks"]["answerable_declared"] == r["checks"]["answerable_expected"]
    )
    unanswerable = [r for r in followups if r["checks"]["answerable_expected"] is False]
    refusals_ok = sum(
        1 for r in unanswerable
        if r["checks"]["answerable_declared"] is False and r["checks"]["refusal_cue_found"]
    )
    overclaims = sum(1 for r in followups if r["checks"].get("overclaim"))
    rewrites = [r for r in records if r["task"] == "rewrite"]
    value_checked = value_kept = 0
    for record in rewrites:
        facts = CASES.get(record["case_id"], {}).get("facts") or {}
        value = facts.get("value_text")
        if value and facts.get("value_confirmed"):
            value_checked += 1
            text = (record["response"] or {}).get("rewritten_explanation", "")
            if value in text:
                value_kept += 1
    leaks = sum(
        1 for r in rewrites
        if "[mp_" in (r["response"] or {}).get("rewritten_explanation", "")
        or "(mp_" in (r["response"] or {}).get("rewritten_explanation", "")
    )
    latencies = sorted(r["metrics"]["total_ms"] for r in records)
    ttfts = [r["metrics"]["ttft_ms"] for r in records if r["metrics"]["ttft_ms"] is not None]
    tps = [r["metrics"]["tokens_per_second"] for r in records if r["metrics"]["tokens_per_second"]]
    rss = [r["metrics"]["peak_rss_mb"] for r in records if r["metrics"]["peak_rss_mb"]]
    out_tokens = [r["metrics"]["eval_count"] for r in records if r["metrics"]["eval_count"]]
    return {
        "runs": total,
        "schema_valid": schema,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else None,
        "overclaims": overclaims,
        "answerable_accuracy": round(answerable_ok / len(followups), 4) if followups else None,
        "correct_refusals": f"{refusals_ok}/{len(unanswerable)}",
        "value_kept": f"{value_kept}/{value_checked}",
        "citation_leaks": leaks,
        "number_violations": sum(len(r["checks"]["number_violations"]) for r in records),
        "safety_violations": sum(len(r["checks"]["safety_categories"]) for r in records),
        "permission_violations": sum(len(r["checks"]["permission_phrase_hits"]) for r in records),
        "source_violations": sum(len(r["checks"]["source_violations"]) for r in records),
        "median_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_latency_ms": round(latencies[int(len(latencies) * 0.95) - 1], 1) if latencies else None,
        "median_ttft_ms": round(statistics.median(ttfts), 1) if ttfts else None,
        "median_tps": round(statistics.median(tps), 2) if tps else None,
        "peak_rss_mb": round(max(rss), 1) if rss else None,
        "median_output_tokens": int(statistics.median(out_tokens)) if out_tokens else None,
        "failures": [
            {"case": r["case_id"], "violations": r["checks"]["violations"],
             "schema_error": r.get("schema_error")}
            for r in records if not r["checks"]["passed"]
        ],
    }


def main() -> int:
    records = load_records()
    by_model: dict[str, list[dict]] = {}
    for record in records:
        by_model.setdefault(record["model"], []).append(record)

    manifest = {}
    for path in glob.glob(str(BENCH / "*" / "manifest.json")):
        data = json.loads(Path(path).read_text())
        manifest.update(data.get("runtime", {}).get("models", {}))

    cold = {}
    for path in glob.glob(str(ROOT / "eval" / "llm" / "bench" / "cold_start.jsonl")):
        for line in Path(path).read_text().splitlines():
            if line.strip():
                entry = json.loads(line)
                cold[entry["model"]] = entry

    summaries = {}
    for model, rows in by_model.items():
        summary = summarise(rows)
        info = manifest.get(model, {})
        summary.update({
            "params": info.get("parameter_size"),
            "quantization": info.get("quantization_level"),
            "size_gb": info.get("size_gb"),
            "digest": info.get("digest", "")[:16],
            "cold_load_ms": cold.get(model, {}).get("load_ms"),
            "cold_total_ms": cold.get(model, {}).get("cold_wall_ms"),
        })
        summaries[model] = summary

    out = {"models": summaries, "records": len(records)}
    (BENCH / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("| Model | Params | Size | Schema | Pass | Over-claim | Answerable | Refusals | Value kept | Num/Safety/Perm/Source | Median | p95 | TTFT | tok/s | RSS | Cold load |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for model, s in sorted(summaries.items()):
        print(f"| `{model}` | {s['params']} | {s['size_gb']} GB | {s['schema_valid']}/{s['runs']} | "
              f"{s['passed']}/{s['runs']} | {s['overclaims']} | {s['answerable_accuracy']} | "
              f"{s['correct_refusals']} | {s['value_kept']} | "
              f"{s['number_violations']}/{s['safety_violations']}/{s['permission_violations']}/{s['source_violations']} | "
              f"{s['median_latency_ms']} ms | {s['p95_latency_ms']} ms | {s['median_ttft_ms']} ms | "
              f"{s['median_tps']} | {s['peak_rss_mb']} MB | {s['cold_load_ms']} ms |")
    print()
    for model, s in sorted(summaries.items()):
        print(f"\n### {model} failures")
        if not s["failures"]:
            print("  none")
        for failure in s["failures"]:
            print(f"  {failure['case']}: {failure['violations'] or failure['schema_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
