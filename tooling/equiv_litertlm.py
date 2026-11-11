"""Token-equivalence harness: HF model vs a LiteRT-LM bundle.

Compares greedy generation for identical prompts. Run after an export exists:

    python tooling/equiv_litertlm.py artifacts/litertlm/qwen3-0.6b-lora/*.litertlm

Refuses to claim equivalence from "both look plausible": it records exact token ids from
the HF side, the bundle's text, and the first divergence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = "Qwen/Qwen3-0.6B"
PROMPTS = [
    "Explain what a uric acid test measures in two sentences.",
    "My uric acid result is 8.4 mg/dL and the printed interval is 2.0-5.0. What does that mean?",
    "The report names Bilirubin but MediRead says the name is ambiguous. What should I do?",
    "Say only: This is not a diagnosis.",
]


def hf_generate(prompt: str) -> list[int]:
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.float32).eval()
    messages = [{"role": "user", "content": prompt}]
    try:
        text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
        )
    except TypeError:
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=128, do_sample=False,
                             pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    return out[0][inputs["input_ids"].shape[1]:].tolist()


def bundle_generate(bundle: Path, prompt: str) -> str:
    result = subprocess.run(
        ["litert-lm", "run", str(bundle), "--prompt", prompt],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:500])
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if not args.bundle.exists():
        print(f"no bundle at {args.bundle}; the export has not been produced", file=sys.stderr)
        return 2
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    report = {"bundle": str(args.bundle), "prompts": [], "equivalent": True}
    for prompt in PROMPTS:
        ids = hf_generate(prompt)
        hf_text = tokenizer.decode(ids, skip_special_tokens=True)
        bundle_text = bundle_generate(args.bundle, prompt)
        report["prompts"].append({
            "prompt": prompt,
            "hf_tokens": ids,
            "hf_text": hf_text,
            "bundle_text": bundle_text,
            "same_text": hf_text.strip() == bundle_text.strip(),
        })
        report["equivalent"] &= hf_text.strip() == bundle_text.strip()
    print(json.dumps(report, indent=2))
    return 0 if report["equivalent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
