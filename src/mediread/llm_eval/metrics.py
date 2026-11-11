"""Aggregate metrics from saved evaluation records."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

CATEGORY_ORDER = (
    "diagnosis_claim", "treatment_advice", "urgency_claim",
    "prognosis_claim", "false_reassurance",
)


def load_records(run_dir: Path) -> list[dict]:
    records = []
    for path in sorted(Path(run_dir).glob("*/*.json")):
        if path.name.endswith(".summary.json"):
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return [r for r in records if "checks" in r]


def aggregate(records: list[dict], manifest: dict | None = None) -> dict:
    by_model: dict[str, list[dict]] = {}
    for record in records:
        by_model.setdefault(record["model"], []).append(record)

    out = {"models": {}, "records": len(records)}
    for model, rows in by_model.items():
        total = len(rows)
        schema = sum(1 for r in rows if r["checks"]["schema_valid"])
        passed = sum(1 for r in rows if r["checks"]["passed"])
        categories: dict[str, int] = {}
        for row in rows:
            for category in row["checks"]["safety_categories"]:
                categories[category] = categories.get(category, 0) + 1
        followups = [r for r in rows if r["task"] == "followup"]
        answerable_ok = sum(
            1 for r in followups
            if r["checks"]["answerable_declared"] == r["checks"]["answerable_expected"]
        )
        refused_ok = sum(
            1 for r in followups
            if r["checks"]["answerable_expected"] is False
            and r["checks"]["answerable_declared"] is False
            and r["checks"]["refusal_cue_found"]
        )
        unanswerable = sum(1 for r in followups if r["checks"]["answerable_expected"] is False)
        latencies = sorted(r["metrics"]["total_ms"] for r in rows)
        ttfts = [r["metrics"]["ttft_ms"] for r in rows if r["metrics"]["ttft_ms"] is not None]
        tps = [r["metrics"]["tokens_per_second"] for r in rows
               if r["metrics"]["tokens_per_second"] is not None]
        rss = [r["metrics"]["peak_rss_mb"] for r in rows if r["metrics"]["peak_rss_mb"]]
        info = (manifest or {}).get("runtime", {}).get("models", {}).get(model, {})
        out["models"][model] = {
            "model": model,
            "runs": total,
            "schema_valid": schema,
            "schema_valid_rate": round(schema / total, 4),
            "checks_passed": passed,
            "pass_rate": round(passed / total, 4),
            "number_violations": sum(len(r["checks"]["number_violations"]) for r in rows),
            "safety_violations": sum(len(r["checks"]["safety_categories"]) for r in rows),
            "safety_by_category": categories,
            "permission_violations": sum(len(r["checks"]["permission_phrase_hits"]) for r in rows),
            "source_violations": sum(len(r["checks"]["source_violations"]) for r in rows),
            "must_not_include_violations": sum(len(r["checks"]["must_not_include_hits"]) for r in rows),
            "followups": len(followups),
            "answerable_accuracy": round(answerable_ok / len(followups), 4) if followups else None,
            "overclaims": sum(1 for r in followups if r["checks"].get("overclaim")),
            "underclaims": sum(1 for r in followups if r["checks"].get("underclaim")),
            "correct_refusals": refused_ok,
            "unanswerable_cases": unanswerable,
            "correct_refusal_rate": round(refused_ok / unanswerable, 4) if unanswerable else None,
            "latency_ms_median": round(statistics.median(latencies), 1),
            "latency_ms_mean": round(statistics.mean(latencies), 1),
            "latency_ms_p95": round(latencies[int(len(latencies) * 0.95) - 1], 1),
            "ttft_ms_median": round(statistics.median(ttfts), 1) if ttfts else None,
            "tokens_per_second_median": round(statistics.median(tps), 2) if tps else None,
            "peak_rss_mb": round(max(rss), 1) if rss else None,
            "prompt_tokens_median": int(statistics.median(
                [r["metrics"]["prompt_eval_count"] for r in rows if r["metrics"]["prompt_eval_count"]]
            )) if any(r["metrics"]["prompt_eval_count"] for r in rows) else None,
            "output_tokens_median": int(statistics.median(
                [r["metrics"]["eval_count"] for r in rows if r["metrics"]["eval_count"]]
            )) if any(r["metrics"]["eval_count"] for r in rows) else None,
            "storage_gb": info.get("size_gb"),
            "parameters": info.get("parameter_size"),
            "quantization": info.get("quantization_level"),
            "digest": info.get("digest"),
            "failures": [
                {"case_id": r["case_id"],
                 "violations": r["checks"]["violations"],
                 "schema_error": r.get("schema_error")}
                for r in rows if not r["checks"]["passed"]
            ],
        }
    return out


def per_case_matrix(records: list[dict]) -> dict[str, dict[str, str]]:
    matrix: dict[str, dict[str, str]] = {}
    for record in records:
        matrix.setdefault(record["case_id"], {})[record["model"]] = (
            "PASS" if record["checks"]["passed"] else "FAIL"
        )
    return matrix
