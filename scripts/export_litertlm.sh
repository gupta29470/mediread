#!/usr/bin/env bash
# Export the merged LoRA Qwen3-0.6B to a .litertlm bundle using the official
# litert-torch workflow. Run inside the Linux container from docker/Dockerfile.export.
#
# Usage: scripts/export_litertlm.sh [model_dir] [out_dir]
set -euo pipefail

MODEL_DIR="${1:-artifacts/training/lora-qwen3-0.6b/merged-fp16}"
OUT_DIR="${2:-artifacts/litertlm/qwen3-0.6b-lora}"
METADATA_URL="https://raw.githubusercontent.com/google-ai-edge/LiteRT-LM/main/models/qwen3/LlmMetadataProto.pbtext"

mkdir -p "$OUT_DIR" .cache/litertlm
if [[ ! -f .cache/litertlm/LlmMetadataProto.pbtext ]]; then
  curl -fsSL "$METADATA_URL" -o .cache/litertlm/LlmMetadataProto.pbtext
fi

echo "== environment"
python - <<'PY'
import sys, torch, transformers, tensorflow, peft, litert_torch
import importlib.metadata as md
print("python", sys.version.split()[0])
print("torch", torch.__version__)
print("transformers", transformers.__version__)
print("tensorflow", tensorflow.__version__)
print("peft", peft.__version__)
print("litert-torch", md.version("litert-torch"))
print("litert-lm", md.version("litert-lm"))
PY

echo "== export (quantization: dynamic_wi4_afp32)"
python -m litert_torch.generative.export_hf \
  --model="$MODEL_DIR" \
  --litert_lm_llm_metadata_override=.cache/litertlm/LlmMetadataProto.pbtext \
  --quantization_recipe=dynamic_wi4_afp32 \
  --output_dir="$OUT_DIR"

echo "== inspect"
litert-lm describe "$OUT_DIR" 2>/dev/null || true
python - "$OUT_DIR" <<'PY'
from pathlib import Path
import hashlib, json, sys
out = Path(sys.argv[1])
bundles = sorted(out.rglob("*.litertlm"))
print(json.dumps({
    "bundles": [str(p) for p in bundles],
    "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in bundles},
    "bytes": {p.name: p.stat().st_size for p in bundles},
}, indent=2))
PY
