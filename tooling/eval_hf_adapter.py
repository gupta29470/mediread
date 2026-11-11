"""Before/after evaluation of the LoRA adapter on the frozen 21-case benchmark.

Runs the *same* HF model (fp32, greedy) with and without the adapter, so the only
difference is the adapter. The Ollama baseline is a separate, quantised reference.

    python tooling/eval_hf_adapter.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

from mediread.llm_eval import checks, prompts, schema
from mediread.llm_eval.dataset import load_dataset

BASE = "Qwen/Qwen3-0.6B"
ADAPTER = Path("artifacts/training/lora-qwen3-0.6b/adapter")
CASES = Path("data/llm_eval/cases.json")
OUT = Path("artifacts/llm_eval/hf-lora")
MAX_NEW = 400


def _template(tokenizer, messages, *, add_generation_prompt: bool) -> str:
    """Qwen3 defaults to a thinking preamble; the benchmark prompts expect JSON only."""
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=add_generation_prompt,
            enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=add_generation_prompt,
        )


def _strip_think(text: str) -> str:
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).replace("</think>", "").strip()


def generate(model, tokenizer, prompt: str, device: str) -> str:
    messages = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    text = _template(tokenizer, messages, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=2048).to(device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=MAX_NEW, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    return _strip_think(tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True))


def run(label: str, model, tokenizer, cases, device: str) -> dict:
    records = []
    passed = schema_ok = 0
    numeric = permission = safety = 0
    durations = []
    for case in cases:
        started = time.perf_counter()
        example = (
            '{"rewritten_explanation": "plain-language rewrite", '
            '"used_source_ids": ["mp_lab_cbc"], "limitations_acknowledged": true}'
            if case.task == "rewrite" else
            '{"answer": "direct answer", "answerable_from_context": true, '
            '"used_source_ids": [], "limitation": ""}'
        )
        user_prompt = (
            prompts.prompt_for(case)
            + "\n\nRespond with one JSON object and nothing else, in this exact shape:\n"
            + example
        )
        text = generate(model, tokenizer, user_prompt, device)
        elapsed = (time.perf_counter() - started) * 1000
        payload, error = None, None
        try:
            payload = schema.validate_response(case.task, schema.parse_json(text))
        except schema.SchemaError as exc:
            error = str(exc)
        check = checks.evaluate(case, payload or {}, schema_valid=error is None)
        numeric += len(check.number_violations)
        permission += len(check.permission_phrase_hits)
        safety += len(check.safety_categories)
        passed += 1 if check.passed else 0
        schema_ok += 1 if error is None else 0
        durations.append(elapsed)
        records.append({"case_id": case.case_id, "schema_error": error, "response": text,
                        "passed": check.passed, "violations": check.violations})
    result = {
        "label": label,
        "cases": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4),
        "schema_valid": schema_ok,
        "schema_rate": round(schema_ok / len(cases), 4),
        "numeric_violations": numeric,
        "permission_violations": permission,
        "safety_violations": safety,
        "median_ms": round(sorted(durations)[len(durations) // 2], 1),
        "records": records,
    }
    print(f"{label:22} pass {passed}/{len(cases)} schema {schema_ok}/{len(cases)} "
          f"num={numeric} perm={permission} safety={safety} median={result['median_ms']}ms")
    return result


def main() -> int:
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dataset = load_dataset(CASES)
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.float32).to(device).eval()
    OUT.mkdir(parents=True, exist_ok=True)

    before = run("hf-base", base, tokenizer, dataset.cases, device)
    tuned = PeftModel.from_pretrained(base, ADAPTER).to(device).eval()
    after = run("hf-base+lora", tuned, tokenizer, dataset.cases, device)

    summary = {
        "base_model": BASE,
        "adapter": str(ADAPTER),
        "device": device,
        "precision": "float32",
        "before": {k: v for k, v in before.items() if k != "records"},
        "after": {k: v for k, v in after.items() if k != "records"},
        "fixed": [r["case_id"] for r, a in zip(before["records"], after["records"])
                  if not r["passed"] and a["passed"]],
        "regressed": [r["case_id"] for r, a in zip(before["records"], after["records"])
                      if r["passed"] and not a["passed"]],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (OUT / "records.jsonl").write_text("\n".join(
        json.dumps({"stage": stage, **record}) for stage, result in (("before", before), ("after", after))
        for record in result["records"]) + "\n")
    print("fixed:", summary["fixed"])
    print("regressed:", summary["regressed"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
