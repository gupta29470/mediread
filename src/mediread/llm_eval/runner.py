"""Run every model over the fixed dataset and persist raw, auditable records."""

from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from . import client, prompts
from .checks import evaluate
from .schema import SchemaError, parse_json, validate_response

MODELS = ("gemma4:e2b", "gemma4:e4b", "qwen3.5:4b")


def slug(model: str) -> str:
    return model.replace(":", "-").replace("/", "-")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_model(
    model: str,
    cases: Iterable,
    out_dir: Path,
    *,
    progress: Callable[[str], None] = print,
    repeat: int = 1,
    warmup: bool = True,
) -> dict:
    model_dir = Path(out_dir) / slug(model)
    model_dir.mkdir(parents=True, exist_ok=True)
    cases = list(cases)
    records = []

    if warmup:
        progress(f"[{model}] warmup (load model, not scored)")
        client.chat(
            model=model,
            system=prompts.SYSTEM_PROMPT,
            user="Return {\"ok\": true}.",
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"], "additionalProperties": False},
        )

    for index, case in enumerate(cases, 1):
        for attempt in range(1, repeat + 1):
            user_prompt = prompts.prompt_for(case)
            started = time.perf_counter()
            generation = client.chat(
                model=model,
                system=prompts.SYSTEM_PROMPT,
                user=user_prompt,
                schema=prompts.schema_for(case),
            )
            payload = None
            schema_error = None
            schema_valid = False
            try:
                payload = parse_json(generation.text)
                payload = validate_response(case.task, payload)
                schema_valid = True
            except SchemaError as exc:
                schema_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                schema_error = f"{type(exc).__name__}: {exc}"

            checks = evaluate(case, payload or {}, schema_valid=schema_valid)
            record = {
                "case_id": case.case_id,
                "model": model,
                "task": case.task,
                "scenario": case.scenario,
                "attempt": attempt,
                "dataset_version": "mediread.llm-eval/1",
                "prompt_version": prompts.PROMPT_VERSION,
                "created_at": _now(),
                "request": {
                    "system": prompts.SYSTEM_PROMPT,
                    "user": user_prompt,
                    "schema": prompts.schema_for(case),
                    "options": client.GENERATION_OPTIONS,
                },
                "response_raw": generation.text,
                "response": payload,
                "schema_error": schema_error,
                "metrics": generation.to_dict(),
                "wall_ms": round((time.perf_counter() - started) * 1000.0, 1),
                "checks": checks.to_dict(),
            }
            name = f"{case.case_id}.json" if repeat == 1 else f"{case.case_id}.run{attempt}.json"
            (model_dir / name).write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            records.append(record)
            status = "PASS" if checks.passed else "FAIL"
            progress(
                f"[{model}] {index:>2}/{len(cases)} {case.case_id:34s} {status:4s} "
                f"{record['metrics']['total_ms']:>7.0f}ms "
                f"ttft={record['metrics']['ttft_ms']} tok/s={record['metrics']['tokens_per_second']}"
            )

    return _summarise(model, records)


def _summarise(model: str, records: list[dict]) -> dict:
    total = len(records)
    schema_ok = sum(1 for record in records if record["checks"]["schema_valid"])
    passed = sum(1 for record in records if record["checks"]["passed"])
    numbers = sum(len(record["checks"]["number_violations"]) for record in records)
    safety = sum(len(record["checks"]["safety_categories"]) for record in records)
    permission = sum(len(record["checks"]["permission_phrase_hits"]) for record in records)
    followups = [r for r in records if r["task"] == "followup"]
    answerable_ok = sum(
        1 for r in followups
        if r["checks"]["answerable_declared"] == r["checks"]["answerable_expected"]
    )
    latencies = sorted(r["metrics"]["total_ms"] for r in records)
    ttfts = [r["metrics"]["ttft_ms"] for r in records if r["metrics"]["ttft_ms"] is not None]
    tps = [r["metrics"]["tokens_per_second"] for r in records
           if r["metrics"]["tokens_per_second"] is not None]
    rss = [r["metrics"]["peak_rss_mb"] for r in records if r["metrics"]["peak_rss_mb"]]
    prompt_tokens = [r["metrics"]["prompt_eval_count"] for r in records
                     if r["metrics"]["prompt_eval_count"]]
    output_tokens = [r["metrics"]["eval_count"] for r in records if r["metrics"]["eval_count"]]
    return {
        "model": model,
        "runs": total,
        "schema_valid": schema_ok,
        "schema_valid_rate": round(schema_ok / total, 4) if total else None,
        "checks_passed": passed,
        "pass_rate": round(passed / total, 4) if total else None,
        "number_violations": numbers,
        "safety_violations": safety,
        "permission_violations": permission,
        "followups": len(followups),
        "answerable_accuracy": round(answerable_ok / len(followups), 4) if followups else None,
        "latency_ms_median": round(statistics.median(latencies), 1) if latencies else None,
        "latency_ms_p95": round(latencies[int(len(latencies) * 0.95) - 1], 1) if latencies else None,
        "ttft_ms_median": round(statistics.median(ttfts), 1) if ttfts else None,
        "tokens_per_second_median": round(statistics.median(tps), 2) if tps else None,
        "peak_rss_mb": round(max(rss), 1) if rss else None,
        "prompt_tokens_median": int(statistics.median(prompt_tokens)) if prompt_tokens else None,
        "output_tokens_median": int(statistics.median(output_tokens)) if output_tokens else None,
        "failures": [
            {"case_id": r["case_id"], "violations": r["checks"]["violations"],
             "schema_error": r["schema_error"]}
            for r in records if not r["checks"]["passed"]
        ],
    }


def run_all(
    dataset,
    out_dir: Path,
    *,
    models: Iterable[str] = MODELS,
    progress: Callable[[str], None] = print,
    repeat: int = 1,
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = client.runtime_metadata()
    manifest = {
        "started_at": _now(),
        "dataset_version": dataset.version,
        "knowledge_version": dataset.knowledge_version,
        "prompt_version": prompts.PROMPT_VERSION,
        "generation_options": client.GENERATION_OPTIONS,
        "runtime": metadata,
        "case_count": len(dataset.cases),
        "case_ids": [case.case_id for case in dataset.cases],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summaries = []
    for model in models:
        progress(f"=== {model} ({metadata['models'].get(model, {}).get('size_gb', '?')} GB)")
        summary = run_model(model, dataset.cases, out_dir, progress=progress, repeat=repeat)
        summaries.append(summary)

    (out_dir / "summary.json").write_text(
        json.dumps({"manifest": manifest, "models": summaries,
                    "finished_at": _now()}, indent=2),
        encoding="utf-8",
    )
    return {"manifest": manifest, "models": summaries}
