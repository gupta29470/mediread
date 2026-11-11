#!/usr/bin/env python
"""Generate a markdown report from a saved evaluation run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.llm_eval.metrics import aggregate, load_records, per_case_matrix  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default=str(ROOT / "eval" / "llm" / "run1"))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    run_dir = Path(args.run)
    records = load_records(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = aggregate(records, manifest)
    matrix = per_case_matrix(records)

    lines = ["# LLM evaluation run", ""]
    runtime = manifest["runtime"]
    lines += [
        f"- Ollama: `{runtime['ollama_version']}`",
        f"- Dataset: `{manifest['dataset_version']}` ({manifest['case_count']} cases)",
        f"- Prompt: `{manifest['prompt_version']}`",
        f"- Generation: `{json.dumps(manifest['generation_options'])}`",
        "",
        "## Models as actually loaded",
        "",
        "| Tag | Params | Quant | Size (GB) | Digest |",
        "|---|---|---|---|---|",
    ]
    for model, summary_row in summary["models"].items():
        lines.append(
            f"| `{model}` | {summary_row['parameters']} | {summary_row['quantization']} | "
            f"{summary_row['storage_gb']} | `{summary_row['digest'][:16]}` |"
        )

    lines += [
        "",
        "## Automated results",
        "",
        "| Model | Schema | Pass | Num. violations | Safety | Permission | Source | Overclaims | Answerable acc. | Correct refusals |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model, row in summary["models"].items():
        lines.append(
            f"| `{model}` | {row['schema_valid_rate']:.2f} | {row['pass_rate']:.2f} | "
            f"{row['number_violations']} | {row['safety_violations']} | "
            f"{row['permission_violations']} | {row['source_violations']} | "
            f"{row['overclaims']} | {row['answerable_accuracy']} | "
            f"{row['correct_refusals']}/{row['unanswerable_cases']} |"
        )

    lines += [
        "",
        "## Performance",
        "",
        "| Model | Median latency (ms) | p95 (ms) | TTFT (ms) | tok/s | Peak RSS (MB) | Prompt tok | Output tok |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for model, row in summary["models"].items():
        lines.append(
            f"| `{model}` | {row['latency_ms_median']} | {row['latency_ms_p95']} | "
            f"{row['ttft_ms_median']} | {row['tokens_per_second_median']} | "
            f"{row['peak_rss_mb']} | {row['prompt_tokens_median']} | {row['output_tokens_median']} |"
        )

    models = list(summary["models"])
    lines += ["", "## Per-case matrix", "",
              "| Case | " + " | ".join(f"`{m}`" for m in models) + " |",
              "|---|" + "---|" * len(models)]
    for case_id in sorted(matrix):
        row = matrix[case_id]
        lines.append(f"| {case_id} | " + " | ".join(row.get(m, "-") for m in models) + " |")

    lines += ["", "## Failures", ""]
    for model, row in summary["models"].items():
        if not row["failures"]:
            lines.append(f"- `{model}`: none")
            continue
        for failure in row["failures"]:
            lines.append(
                f"- `{model}` / {failure['case_id']}: {failure['violations'] or failure['schema_error']}"
            )

    text = "\n".join(lines) + "\n"
    out = Path(args.out) if args.out else run_dir / "report.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
