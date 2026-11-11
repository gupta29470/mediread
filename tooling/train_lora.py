"""Reproducible LoRA fine-tuning of Qwen3-0.6B on the MediRead SFT set.

Deliberately small and boring: transformers + peft, no trainer tricks, deterministic
seeds, validation-loss checkpoint selection, and the frozen benchmark never touched.

    python tooling/train_lora.py --smoke      # 4 steps, sanity check
    python tooling/train_lora.py             # full run (2 epochs)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen3-0.6B"
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
DATASET = Path("datasets/mediread-sft-v0")
OUT = Path("artifacts/training/lora-qwen3-0.6b")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chat_text(tokenizer, messages: list[dict]) -> str:
    try:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False, enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)


def encode(tokenizer, text: str, max_len: int) -> dict:
    encoded = tokenizer(text, truncation=True, max_length=max_len, padding=False, return_tensors=None)
    encoded["labels"] = list(encoded["input_ids"])
    return encoded


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--max-len", type=int, default=512)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.float32)
    model.to(device)
    model.gradient_checkpointing_enable()
    model.config.use_cache = False

    lora = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout,
        target_modules=TARGET_MODULES, bias="none", task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_rows = [json.loads(line) for line in (DATASET / "train.jsonl").read_text().splitlines()]
    val_rows = [json.loads(line) for line in (DATASET / "validation.jsonl").read_text().splitlines()]
    if args.smoke:
        train_rows, val_rows = train_rows[:4], val_rows[:2]

    def batches(rows, batch_size):
        for index in range(0, len(rows), batch_size):
            yield rows[index:index + batch_size]

    optimiser = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / ("smoke_log.jsonl" if args.smoke else "train_log.jsonl")
    log_path.write_text("")
    started = time.time()
    best_loss = float("inf")
    step = 0
    eval_history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        for batch_rows in batches(train_rows, args.batch):
            texts = [chat_text(tokenizer, row["messages"]) for row in batch_rows]
            encoded = [encode(tokenizer, text, args.max_len) for text in texts]
            width = max(len(item["input_ids"]) for item in encoded)
            input_ids = torch.full((len(encoded), width), tokenizer.pad_token_id, dtype=torch.long)
            attention = torch.zeros((len(encoded), width), dtype=torch.long)
            labels = torch.full((len(encoded), width), -100, dtype=torch.long)
            for i, item in enumerate(encoded):
                length = len(item["input_ids"])
                input_ids[i, :length] = torch.tensor(item["input_ids"])
                attention[i, :length] = 1
                labels[i, :length] = torch.tensor(item["labels"])
            outputs = model(input_ids=input_ids.to(device), attention_mask=attention.to(device),
                            labels=labels.to(device))
            loss = outputs.loss / args.grad_accum
            loss.backward()
            step += 1
            if step % args.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
                optimiser.step()
                optimiser.zero_grad(set_to_none=True)
            with log_path.open("a") as handle:
                handle.write(json.dumps({"step": step, "epoch": epoch, "loss": round(float(loss) * args.grad_accum, 5)}) + "\n")
            if step % 10 == 0:
                print(f"step {step} epoch {epoch} loss {float(loss) * args.grad_accum:.4f}", flush=True)
            if args.smoke and step >= 8:
                break
        if args.smoke:
            break

        model.eval()
        total, count = 0.0, 0
        with torch.no_grad():
            for row in val_rows:
                text = chat_text(tokenizer, row["messages"])
                item = encode(tokenizer, text, args.max_len)
                ids = torch.tensor([item["input_ids"]]).to(device)
                mask = torch.ones_like(ids)
                labels = torch.tensor([item["labels"]]).to(device)
                loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
                total += float(loss)
                count += 1
        val_loss = total / max(count, 1)
        eval_history.append({"epoch": epoch, "val_loss": round(val_loss, 5)})
        print(f"epoch {epoch} validation loss {val_loss:.4f}", flush=True)
        if val_loss < best_loss:
            best_loss = val_loss
            model.save_pretrained(OUT / "adapter")
            tokenizer.save_pretrained(OUT / "adapter")

    config = {
        "base_model": BASE_MODEL,
        "base_revision": "main",
        "licence": "Apache-2.0 (Qwen3-0.6B model card)",
        "lora": {"r": args.rank, "alpha": args.alpha, "dropout": args.dropout,
                 "target_modules": TARGET_MODULES, "bias": "none", "task_type": "CAUSAL_LM"},
        "training": {"epochs": args.epochs, "batch": args.batch, "grad_accum": args.grad_accum,
                     "lr": args.lr, "max_len": args.max_len, "optimizer": "AdamW",
                     "seed": args.seed, "device": device, "precision": "float32"},
        "dataset": {"version": "mediread-sft-v0",
                    "train_sha256": sha256(DATASET / "train.jsonl"),
                    "validation_sha256": sha256(DATASET / "validation.jsonl"),
                    "train_examples": len(train_rows), "validation_examples": len(val_rows)},
        "eval_history": eval_history,
        "best_val_loss": round(best_loss, 5) if best_loss < float("inf") else None,
        "wall_seconds": round(time.time() - started, 1),
        "smoke": args.smoke,
    }
    (OUT / ("smoke_config.json" if args.smoke else "config.json")).write_text(json.dumps(config, indent=2) + "\n")
    print(json.dumps(config, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
