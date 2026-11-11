#!/usr/bin/env python3
"""Run the 22-case production contract benchmark against a LiteRT-LM bundle.

Reference: the merged Qwen3-0.6B LoRA checkpoint in FP32 (HF greedy decoding).
Candidate: artifacts/quant/model-wo8.litertlm (weight_only_wi8_afp32, 0.61 GB).

Both paths share the case construction, prompt rendering (production
`build_model_input` + `prompt_for` + chat template), greedy sampling and stop rules
from `tooling/eval_contract.py`; nothing there is modified.

    PYTHONPATH=src python tooling/eval_bundle_contract.py --cases 22
    PYTHONPATH=src python tooling/eval_bundle_contract.py --limit 2   # smoke test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tooling.eval_contract import (  # noqa: E402
    ADAPTER, BASE, DB, MAX_NEW, build_cases, prompt_for, template, validate,
)
from mediread.explain.package_provider import EVALUATION_STATUSES, PackageProvider  # noqa: E402

CKPT = Path("artifacts/training/lora-qwen3-0.6b/merged-fp16")
BUNDLE = Path("artifacts/quant/model-wo8.litertlm")
OUT = Path("artifacts/eval-bundle-contract")

CAUSES = ("wording_only", "additional_claim", "factual_deviation", "refusal_deviation",
          "permission_violation", "formatting", "runtime_failure")


def hf_generate(model, tokenizer, rendered: str) -> dict:
    inputs = tokenizer(rendered, return_tensors="pt", truncation=True, max_length=2048)
    started = time.perf_counter()
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=MAX_NEW, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    elapsed = (time.perf_counter() - started) * 1000
    ids = out[0][inputs["input_ids"].shape[1]:].tolist()
    text = tokenizer.decode(ids, skip_special_tokens=True)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).replace("</think>", "").strip()
    return {"ids": ids, "text": text, "ms": round(elapsed, 1),
            "prompt_ids": inputs["input_ids"][0].tolist(),
            "stopped": bool(ids) and ids[-1] == tokenizer.eos_token_id,
            "generated_tokens": len(ids)}


def bundle_generate(engine, rendered: str) -> dict:
    import litert_lm as L
    started = time.perf_counter()
    prompt_ids = engine.tokenize(rendered)
    session = engine.create_session(
        apply_prompt_template=False,
        sampler_config=L.SamplerConfig(temperature=0.0, top_k=1, top_p=1.0, seed=42),
        max_output_tokens=MAX_NEW,
    )
    session.run_prefill([rendered])
    response = session.run_decode()
    elapsed = (time.perf_counter() - started) * 1000
    text = "".join(response.texts).strip()
    generated = int(response.token_lengths[-1]) if response.token_lengths else 0
    ids = engine.tokenize(text)
    session.close()
    return {"ids": ids, "text": text, "prompt_ids": prompt_ids, "ms": round(elapsed, 1),
            "stopped": generated < MAX_NEW, "generated_tokens": generated}


def compare(case: dict, hf: dict, rt: dict) -> dict:
    hf_ids = list(hf["ids"])
    if hf_ids and hf_ids[-1] == 151645:
        hf_ids = hf_ids[:-1]
    rt_ids = list(rt["ids"])
    limit = min(len(hf_ids), len(rt_ids))
    divergence = next((i for i in range(limit) if hf_ids[i] != rt_ids[i]), None)
    if divergence is None and len(hf_ids) != len(rt_ids):
        divergence = limit
    exact = divergence is None

    hf_checks, rt_checks = validate(case, hf["text"]), validate(case, rt["text"])
    causes: list[str] = []
    if not exact:
        # Record every applicable cause, severest first; a case can have several.
        if rt_checks["permission_violation"]:
            causes.append("permission_violation")
        if rt_checks["numeric_violations"]:
            causes.append("factual_deviation")
        if case["kind"] == "refusal" and not rt_checks["refusal_ok"]:
            causes.append("refusal_deviation")
        if not causes:
            if not rt_checks["format_ok"]:
                causes.append("formatting")
            elif hf_checks["correct"] and rt_checks["correct"]:
                causes.append("wording_only")
            else:
                causes.append("additional_claim")

    return {
        "case_id": case["case_id"], "kind": case["kind"],
        "expected": "answerable" if case["kind"] == "answerable" else case["kind"],
        "hf_ids": hf_ids, "hf_text": hf["text"], "hf_ms": hf["ms"],
        "hf_stopped_on_eos": hf["stopped"], "hf_generated_tokens": hf["generated_tokens"],
        "rt_ids": rt_ids, "rt_text": rt["text"], "rt_ms": rt["ms"],
        "rt_stopped": rt["stopped"], "rt_generated_tokens": rt["generated_tokens"],
        "prompt_ids_match_hf": rt.get("prompt_ids") == hf.get("prompt_ids"),
        "exact_token_match": exact, "first_divergence": divergence,
        "hf_checks": hf_checks, "rt_checks": rt_checks,
        "causes": causes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=22)
    parser.add_argument("--bundle", type=Path, default=BUNDLE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    provider = PackageProvider.open(DB, include_statuses=EVALUATION_STATUSES)
    cases = build_cases(provider)[: args.limit]
    args.out.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(CKPT)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(CKPT, torch_dtype=torch.float32).eval()

    import litert_lm as L
    engine = L.Engine(str(args.bundle), backend=L.Backend.CPU, max_num_tokens=2048)

    records, errors = [], []
    for index, case in enumerate(cases, 1):
        prompt = prompt_for(case["model_input"])
        rendered = template(tokenizer, prompt)
        try:
            hf = hf_generate(model, tokenizer, rendered)
        except Exception as exc:  # pragma: no cover - runtime failure path
            errors.append({"case_id": case["case_id"], "stage": "hf",
                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            rt = bundle_generate(engine, rendered)
        except Exception as exc:
            errors.append({"case_id": case["case_id"], "stage": "litert",
                           "error": f"{type(exc).__name__}: {exc}",
                           "traceback": traceback.format_exc()[-2000:]})
            continue
        record = compare(case, hf, rt)
        record["input_mode"] = "model_input/1"
        records.append(record)
        print(f"[{index:2}/{len(cases)}] {case['case_id']:28} exact={record['exact_token_match']!s:5} "
              f"hf_ok={record['hf_checks']['correct']!s:5} rt_ok={record['rt_checks']['correct']!s:5} "
              f"causes={record['causes']}")

    summary = {
        "contract": "mediread.model-input/1",
        "bundle": str(args.bundle),
        "bundle_bytes": args.bundle.stat().st_size if args.bundle.exists() else None,
        "reference": str(CKPT), "precision": "float32",
        "decoding": {"greedy": True, "max_new_tokens": MAX_NEW, "temperature": 0.0,
                     "top_k": 1, "top_p": 1.0, "seed": 42},
        "cases_expected": len(cases), "cases_run": len(records),
        "errors": errors,
        "exact_token_match": sum(1 for r in records if r["exact_token_match"]),
        "hf_correct": sum(1 for r in records if r["hf_checks"]["correct"]),
        "rt_correct": sum(1 for r in records if r["rt_checks"]["correct"]),
        "numeric_violations": sum(len(r["rt_checks"]["numeric_violations"]) for r in records),
        "permission_violations": sum(1 for r in records if r["rt_checks"]["permission_violation"]),
        "fabricated_sources": sum(1 for r in records if r["rt_checks"]["fabricated_sources"]),
        "format_failures": sum(1 for r in records if not r["rt_checks"]["format_ok"]),
        "refusal_ok": sum(1 for r in records
                          if r["kind"] != "answerable" and r["rt_checks"]["refusal_ok"]),
        "refusal_cases": sum(1 for r in records if r["kind"] != "answerable"),
        "causes": {name: sum(1 for r in records if name in r["causes"]) for name in CAUSES},
        "median_ms_litert": round(sorted(r["rt_ms"] for r in records)[len(records) // 2], 1)
                            if records else None,
        "records": records,
    }
    (args.out / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (args.out / "records.jsonl").open("w") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, indent=2))
    return 0 if len(records) == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
