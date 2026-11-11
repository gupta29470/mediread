"""Token-level acceptance harness for a .litertlm bundle (runtime venv only).

Requires: litert_lm (0.19.1) + a reference.json produced by tooling/hf_reference.py.

    python tooling/validate_bundle.py --bundle model.litertlm \
        --reference artifacts/eval-hf/reference.json --max-tokens 128
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import litert_lm as L

MAX_TOKENS = 128
NGRAW = 3


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", text.lower()))


def jaccard(a: str, b: str) -> float:
    left, right = words(a), words(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def repeated_ngrams(text: str, n: int = NGRAW, limit: int = 3) -> int:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    grams = Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))
    return max(grams.values()) if grams else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--reference", default=Path("artifacts/eval-hf/reference.json"), type=Path)
    parser.add_argument("--max-tokens", type=int, default=MAX_TOKENS)
    parser.add_argument("--out", default=Path("artifacts/eval-hf/bundle-validation.json"), type=Path)
    args = parser.parse_args()

    reference = json.loads(args.reference.read_text())["records"]
    engine = L.Engine(str(args.bundle), backend=L.Backend.CPU, max_num_tokens=2048)
    eos_ids = [item for group in engine.eos_token_ids for item in (group if isinstance(group, (list, tuple)) else [group])]

    results, failures = [], 0
    for record in reference:
        rendered = record["rendered_prompt"]
        prompt_ids = engine.tokenize(rendered)
        prompt_ids_match = prompt_ids == record["prompt_tokens"]

        session = engine.create_session(
            apply_prompt_template=False,
            sampler_config=L.SamplerConfig(temperature=0.0, top_k=1, top_p=1.0, seed=42),
            max_output_tokens=args.max_tokens,
        )
        session.run_prefill([rendered])
        response = session.run_decode()
        text = "".join(response.texts).strip()
        generated_ids = engine.tokenize(text)

        hf_ids = record["generated_ids"]
        # The HF reference includes the trailing EOS token; LiteRT ids come from
        # re-tokenizing text, so the EOS has no textual form. Strip it from both
        # before comparing, otherwise the only "divergence" is the final EOS slot.
        if hf_ids and hf_ids[-1] in eos_ids:
            hf_ids = hf_ids[:-1]
        if generated_ids and generated_ids[-1] in eos_ids:
            generated_ids = generated_ids[:-1]
        limit = min(20, len(hf_ids), len(generated_ids))
        first_divergence = next((i for i in range(limit) if hf_ids[i] != generated_ids[i]), None)
        if first_divergence is None and len(generated_ids) != len(hf_ids):
            first_divergence = limit

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        repeated_line = max(Counter(lines).values()) if lines else 0
        ascii_ratio = sum(1 for ch in text if ord(ch) < 128) / max(len(text), 1)
        stopped_naturally = len(generated_ids) < args.max_tokens - 1

        checks = {
            "prompt_ids_identical": prompt_ids_match,
            "first_20_ids_match": first_divergence is None,
            "eos_generated_naturally": stopped_naturally,
            "english": ascii_ratio >= 0.8,
            "no_sentence_loop": repeated_line <= 3,
            "no_ngram_loop": repeated_ngrams(text) <= 3,
            "semantic_match": jaccard(text, record["text"]) >= 0.35,
        }
        failed = [name for name, ok in checks.items() if not ok]
        failures += len(failed)
        results.append({
            "prompt": record["prompt"],
            "checks": checks,
            "failed": failed,
            "first_divergence_index": first_divergence,
            "hf_first_20_ids": hf_ids[:20],
            "litert_first_20_ids": generated_ids[:20],
            "hf_first_20_tokens": [engine.detokenize([i]) for i in hf_ids[:20]],
            "litert_first_20_tokens": [engine.detokenize([i]) for i in generated_ids[:20]],
            "termination": {
                "generated_tokens": len(generated_ids),
                "max_tokens": args.max_tokens,
                "eos_generated": stopped_naturally,
                "eos_ids": eos_ids,
            },
            "hf_text": record["text"],
            "litert_text": text,
            "ascii_ratio": round(ascii_ratio, 3),
            "max_repeated_line": repeated_line,
            "max_repeated_3gram": repeated_ngrams(text),
            "jaccard_vs_hf": round(jaccard(text, record["text"]), 3),
        })
        print(f"\n=== {record['prompt'][:46]}")
        print(f"  first divergence: {first_divergence} | tokens {len(generated_ids)}/{args.max_tokens}")
        print(f"  failed: {failed or 'none'}")
        print(f"  litert: {text[:160]!r}")

    summary = {"bundle": str(args.bundle), "max_tokens": args.max_tokens,
               "results": results, "failures": failures}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nwrote {args.out}; failed checks: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
