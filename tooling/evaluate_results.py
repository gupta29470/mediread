#!/usr/bin/env python
"""Evaluate structured laboratory extraction against verified ground truth.

Usage:
    python tooling/evaluate_results.py
    python tooling/evaluate_results.py --split embedded ocr --out eval/results.json

Splits are reported separately where the corpus supports it:

* ``embedded`` — pages whose content came from the PDF text layer;
* ``ocr``      — pages processed through OCR;
* ``hybrid``   — pages merged from both.

The corpus has no scanned laboratory tables, so the ``ocr`` split currently
contains the OCR-derived lines of hybrid cover pages only; that is stated in the
output rather than hidden.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, EVAL_DIR, PROJECT_ROOT  # noqa: E402
from mediread.evaluation.result_metrics import (  # noqa: E402
    aggregate,
    evaluate_document,
    group_by_split,
    load_ground_truth,
)
from mediread.structured.pipeline import StructuredExtractionPipeline  # noqa: E402


def split_of(page_payload: dict) -> str:
    method = page_payload.get("method", "embedded_text")
    if method == "ocr":
        return "ocr"
    if method == "hybrid":
        return "hybrid"
    if method == "empty":
        return "empty"
    return "embedded"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractions", default=str(ARTIFACTS_DIR / "extractions"))
    parser.add_argument("--ground-truth", default=str(PROJECT_ROOT / "data" / "result_ground_truth"))
    parser.add_argument("--out", default=str(EVAL_DIR / "results_eval.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    gt = load_ground_truth(args.ground_truth)
    if not gt:
        raise SystemExit("no result ground truth found")
    report_ids = {report_id for report_id, _ in gt}

    pipeline = StructuredExtractionPipeline()
    per_split: dict[str, list] = {}
    pages_out: list[dict] = []
    all_outcomes = []

    for path in sorted(Path(args.extractions).glob("*.extraction.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["report_id"] not in report_ids:
            continue
        document = pipeline.process(payload)
        outcomes = evaluate_document(document, gt)
        all_outcomes.extend(outcomes)
        page_split = {
            page["page_number"]: split_of(page) for page in payload.get("pages", [])
        }
        for outcome in outcomes:
            per_split.setdefault(page_split.get(outcome.page, "embedded"), []).append(outcome)
            pages_out.append(outcome.to_dict())

    overall = aggregate(all_outcomes)
    by_gt_split = group_by_split(all_outcomes, gt)
    summary = {
        "ground_truth_pages": len(gt),
        "ground_truth_rows": sum(len(v["rows"]) for v in gt.values()),
        "overall": overall.to_dict(),
        "by_input_split": {name: aggregate(items).to_dict() for name, items in sorted(per_split.items())},
        "by_gt_split": {name: aggregate(items).to_dict() for name, items in sorted(by_gt_split.items())},
        "pages": pages_out,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    o = summary["overall"]
    print(f"pages={o['pages']} gt_rows={o['gt_rows']} extracted={o['extracted_rows']} matched={o['matched']}")
    print(
        f"row precision={o['row_precision']:.3f} recall={o['row_recall']:.3f} f1={o['row_f1']:.3f} "
        f"FP={o['false_positives']} FN={o['false_negatives']}"
    )
    for name, stats in o["fields"].items():
        acc = "n/a" if stats["accuracy"] is None else f"{stats['accuracy']:.3f}"
        vp = "n/a" if stats["verified_precision"] is None else f"{stats['verified_precision']:.3f}"
        print(f"  {name:11s} n={stats['total_scored']:>3} accuracy={acc} verified_precision={vp} flagged={stats['flagged']}")
    print(
        f"danger: decimal_corruption={o['decimal_corruption_errors']} "
        f"wrong_assignment={o['wrong_assignment_errors']} "
        f"wrong_fields={o['wrong_fields_total']} verified_wrong={o['wrong_fields_marked_verified']} "
        f"capture_rate={o['uncertainty_capture_rate']}"
    )
    for name, stats in summary["by_gt_split"].items():
        fields = stats["fields"]
        value = fields.get("value", {})
        print(
            f"  [{name}] pages={stats['pages']} rows={stats['gt_rows']} matched={stats['matched']} "
            f"P={stats['row_precision']:.3f} R={stats['row_recall']:.3f} "
            f"value_acc={value.get('accuracy')} verified_wrong={stats['wrong_fields_marked_verified']}"
        )
    for name, stats in summary["by_input_split"].items():
        print(f"  input {name:9s} pages={stats['pages']} matched={stats['matched']}")

    if args.verbose:
        for page in pages_out:
            if page["false_negatives"] or page["false_positives"]:
                print(f"  p{page['page']} {page['report_id'][:8]} FN={page['false_negatives']} FP={page['false_positives']}")
            for field in page["fields"]:
                if not field["correct"]:
                    mark = "VERIFIED-WRONG" if field["verified"] else "flagged"
                    print(
                        f"  p{page['page']} {field['test'][:28]:28s} {field['field']:10s} "
                        f"expected={field['expected']!r} actual={field['actual']!r} [{mark}]"
                    )
    print(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
