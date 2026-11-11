"""Audit the merged HF checkpoint: tokenizer, special tokens, chat template, round trips."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from transformers import AutoTokenizer

CKPT = Path("artifacts/training/lora-qwen3-0.6b/merged-fp16")
OUT = Path("artifacts/eval-hf/checkpoint-audit.json")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    tokenizer = AutoTokenizer.from_pretrained(CKPT)
    files = sorted(p.name for p in CKPT.iterdir() if p.is_file())
    tok_config = json.loads((CKPT / "tokenizer_config.json").read_text())

    special = {
        "bos_token": tokenizer.bos_token,
        "bos_id": tokenizer.bos_token_id,
        "eos_token": tokenizer.eos_token,
        "eos_id": tokenizer.eos_token_id,
        "pad_token": tokenizer.pad_token,
        "pad_id": tokenizer.pad_token_id,
        "unk_token": tokenizer.unk_token,
        "unk_id": tokenizer.unk_token_id,
        "additional_special_tokens": list(getattr(tokenizer, "additional_special_tokens", []) or []),
    }

    round_trips = {}
    for text in (
        "Explain what a blood glucose test measures in one sentence.",
        "Haemoglobin (Hb) is measured in g/dL; 13.5–17.5 is a typical printed interval.",
        "HbA1c 5.7 % · eGFR 90 mL/min/1.73m² · CRP < 5 mg/L",
        "café naïve façade — 中文 — русский",
    ):
        ids = tokenizer.encode(text, add_special_tokens=False)
        back = tokenizer.decode(ids, skip_special_tokens=False)
        round_trips[text] = {"ids": ids, "decoded": back, "exact": back == text,
                             "n_tokens": len(ids)}

    chat = {}
    for thinking in (False, True):
        messages = [{"role": "user", "content": "Explain what a haemoglobin test measures in one sentence."}]
        try:
            rendering = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=thinking)
        except TypeError as exc:
            rendering = f"<template does not accept enable_thinking: {exc}>"
        chat[f"thinking={thinking}"] = rendering

    ids = tokenizer.encode(chat["thinking=False"], add_special_tokens=False)
    report = {
        "checkpoint_dir": str(CKPT),
        "files": files,
        "missing_files": [name for name in ("special_tokens_map.json", "tokenizer.json",
                                            "tokenizer_config.json", "chat_template.jinja")
                          if name not in files],
        "hashes": {name: sha256(CKPT / name) for name in files if name.endswith((".json", ".jinja"))},
        "tokenizer_class": type(tokenizer).__name__,
        "vocab_size": len(tokenizer),
        "model_max_length": tokenizer.model_max_length,
        "special_tokens": special,
        "tokenizer_config_subset": {key: tok_config.get(key) for key in
                                    ("model_max_length", "padding_side", "truncation_side",
                                     "clean_up_tokenization_spaces", "eos_token", "pad_token",
                                     "add_bos_token", "chat_template")},
        "chat_template_markers": {
            "<|im_start|>": "<|im_start|>" in (tokenizer.chat_template or ""),
            "<|im_end|>": "<|im_end|>" in (tokenizer.chat_template or ""),
            "enable_thinking": "enable_thinking" in (tokenizer.chat_template or ""),
        },
        "round_trips": round_trips,
        "chat_renderings": chat,
        "generation_prompt_token_count": len(ids),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("files", "missing_files", "tokenizer_class",
                                             "vocab_size", "special_tokens",
                                             "chat_template_markers",
                                             "generation_prompt_token_count")}, indent=2))
    failures = [text for text, info in round_trips.items() if not info["exact"]]
    print("round-trip failures:", len(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
