#!/usr/bin/env python3
"""Quantize an existing .litertlm bundle in place-of-origin, without re-exporting.

Pipeline: unpack -> quantize the prefill/decode .tflite -> repack -> (optionally) validate.

Requires `ai-edge-quantizer` and the LiteRT-LM CLI pinned to the runtime under test
(0.19.1 here). The source checkpoint is never touched; only the bundle's inner .tflite
is rewritten.

Examples
--------
    # baseline: dynamic per-channel int8
    python tooling/quantize_bundle.py --bundle fp32.litertlm --recipe dynamic_wi8_afp32

    # weight-only int8 (best measured fidelity)
    python tooling/quantize_bundle.py --bundle fp32.litertlm --recipe weight_only_wi8_afp32

    # selective: keep EMBEDDING_LOOKUP in fp32, dynamic int8 elsewhere
    python tooling/quantize_bundle.py --bundle fp32.litertlm --recipe dynamic_wi8_afp32 \\
        --keep-fp32 EMBEDDING_LOOKUP

Notes
-----
* Recipe rules are matched in order and the LAST matching rule wins. To leave an
  operation unquantized, append an ``AlgorithmName.NO_QUANTIZE`` rule after the
  default rule (see ``build_recipe``); prepending it has no effect.
* ``--keep-fp32`` accepts ``TFLOperationName`` members (e.g. EMBEDDING_LOOKUP,
  FULLY_CONNECTED) or ``ALL_SUPPORTED``. Keeping the embedding table in fp32 costs
  ~0.62 GB on Qwen3-0.6B and pushes the bundle over 1.5 GB, so it is diagnostic only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

TFLITE_NAME = "Section3_TFLiteModel_tf_lite_prefill_decode.tflite"


def build_recipe(recipe_name: str, keep_fp32: list[str]):
    from ai_edge_quantizer import qtyping, recipe as r

    base = getattr(r, recipe_name)()
    if not keep_fp32:
        return base

    float_rule = {
        "operation": r.TFLOperationName.ALL_SUPPORTED,
        "regex": ".*",
        "algorithm_key": r.AlgorithmName.NO_QUANTIZE,
        "op_config": {
            "compute_precision": qtyping.ComputePrecision.FLOAT,
            "explicit_dequantize": False,
            "min_weight_elements": 0,
            "skip_checks": False,
        },
    }
    rules = list(base)
    for name in keep_fp32:
        op = getattr(r.TFLOperationName, name)
        rules.append({**float_rule, "operation": op})
    return rules


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--recipe", default="weight_only_wi8_afp32")
    parser.add_argument("--keep-fp32", nargs="*", default=[],
                        help="TFLOperationName members to leave in fp32")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workdir", type=Path, default=None)
    parser.add_argument("--litert-lm", default="litert-lm")
    args = parser.parse_args()

    work = args.workdir or args.out.with_suffix(".work")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    subprocess.run([args.litert_lm, "unpack", str(args.bundle), "--output-dir", str(work)],
                   check=True, capture_output=True)
    source = work / TFLITE_NAME
    if not source.exists():
        raise SystemExit(f"missing {TFLITE_NAME} in {work}")

    from ai_edge_quantizer import quantizer as q

    recipe = build_recipe(args.recipe, args.keep_fp32)
    quantized = work / "quantized.tflite"
    qt = q.Quantizer(str(source))
    qt.load_quantization_recipe(recipe)
    qt.quantize(serialize_to_path=str(quantized), enable_progress_bar=False)
    shutil.copy2(quantized, source)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.litert_lm, "pack", str(work), "--output", str(args.out),
                    "--allow-overwrite"], check=True, capture_output=True)

    size = args.out.stat().st_size
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    result = {
        "source_bundle": str(args.bundle),
        "output_bundle": str(args.out),
        "recipe": args.recipe,
        "keep_fp32": args.keep_fp32,
        "bytes": size,
        "gb": round(size / 1e9, 3),
        "sha256": digest,
        "tflite_bytes": source.stat().st_size,
    }
    args.out.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
