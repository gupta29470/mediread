"""Merge a trained LoRA adapter into a standalone checkpoint for export.

The LiteRT-LM exporter expects a normal Hugging Face model directory, not a PEFT
adapter, so the adapter is merged into the base weights and written to
``artifacts/training/lora-qwen3-0.6b/merged-fp16`` by default.

    python tooling/merge_lora.py
    python tooling/merge_lora.py --adapter artifacts/.../adapter --out /tmp/merged
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen3-0.6B"
ADAPTER = Path("artifacts/training/lora-qwen3-0.6b/adapter")
OUT = Path("artifacts/training/lora-qwen3-0.6b/merged-fp16")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=BASE_MODEL)
    parser.add_argument("--adapter", type=Path, default=ADAPTER)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--dtype", choices=["float16", "float32"], default="float16")
    args = parser.parse_args()

    if not (args.adapter / "adapter_config.json").exists():
        parser.error(f"no LoRA adapter at {args.adapter}; run tooling/train_lora.py first")

    dtype = torch.float16 if args.dtype == "float16" else torch.float32
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(args.base, torch_dtype=dtype)
    model = PeftModel.from_pretrained(model, str(args.adapter))
    model = model.merge_and_unload()
    model.eval()

    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(args.out))
    tokenizer.save_pretrained(str(args.out))
    print(f"merged {args.base} + {args.adapter} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
