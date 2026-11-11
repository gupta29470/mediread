"""Greedy reference generation from the merged HF checkpoint on the acceptance prompts."""

from __future__ import annotations

import json
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

CKPT = Path("artifacts/training/lora-qwen3-0.6b/merged-fp16")
OUT = Path("artifacts/eval-hf/reference.json")
PROMPTS = [
    "Explain what a blood glucose test measures in one sentence.",
    "Explain what a haemoglobin test measures in one sentence.",
    "Explain what a cholesterol test measures in one sentence.",
]
MAX_NEW = 96


def main() -> int:
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(CKPT)
    model = AutoModelForCausalLM.from_pretrained(CKPT, torch_dtype=torch.float32).to(device).eval()
    eos_ids = model.generation_config.eos_token_id
    if isinstance(eos_ids, int):
        eos_ids = [eos_ids]

    records = []
    for prompt in PROMPTS:
        messages = [{"role": "user", "content": prompt}]
        text = tokenizer.apply_chat_template(messages, tokenize=False,
                                             add_generation_prompt=True, enable_thinking=False)
        inputs = tokenizer(text, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=MAX_NEW, do_sample=False,
                                 pad_token_id=tokenizer.pad_token_id,
                                 eos_token_id=eos_ids)
        new_ids = out[0][inputs["input_ids"].shape[1]:].tolist()
        stopped_on_eos = bool(new_ids) and new_ids[-1] in (eos_ids or [])
        decoded = tokenizer.decode(new_ids, skip_special_tokens=True).strip()
        records.append({
            "prompt": prompt,
            "rendered_prompt": text,
            "prompt_tokens": inputs["input_ids"][0].tolist(),
            "generated_ids": new_ids,
            "n_generated": len(new_ids),
            "stopped_on_eos": stopped_on_eos,
            "stop_reason": "eos" if stopped_on_eos else "max_new_tokens",
            "text": decoded,
        })
        print(f"\n=== {prompt}\n{decoded}\n[ids={len(new_ids)} eos={stopped_on_eos}]")

    report = {
        "checkpoint": str(CKPT),
        "device": device,
        "decoding": {"do_sample": False, "max_new_tokens": MAX_NEW},
        "eos_token_id": eos_ids,
        "pad_token_id": tokenizer.pad_token_id,
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
