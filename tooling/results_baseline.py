#!/usr/bin/env python
"""Naive baseline: "first number on the row is the value".

Purpose: show what the structural work buys. This baseline does what a quick
implementation would do — reconstruct rows, take the first numeric token as the
value, the next unit-like token as the unit and the last range-like token as the
reference, with the test name being everything before the value.

It is deliberately reasonable, not a straw man: on simple single-row tables it
does well, which is exactly why the comparison is informative.

Usage:
    python tooling/results_baseline.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, EVAL_DIR  # noqa: E402
from mediread.evaluation.result_metrics import (  # noqa: E402
    aggregate,
    evaluate_page,
    load_ground_truth,
)
from mediread.structured.pipeline import document_from_dict  # noqa: E402
from mediread.structured.rows import build_page_tables  # noqa: E402
from mediread.structured.text import looks_numeric, parse_reference  # noqa: E402
from mediread.structured import vocabulary as vocab  # noqa: E402


class BaselineResult:
    """Duck-typed stand-in for LabResult, so the same metrics apply."""

    def __init__(self, test: str, value: str, unit: str | None, reference: str | None):
        from mediread.structured.schema import Field, FieldStatus, ValueKind

        self.test = Field(raw=test, status=FieldStatus.VERIFIED)
        self.value = Field(raw=value, status=FieldStatus.VERIFIED)
        self.unit = Field(raw=unit, status=FieldStatus.VERIFIED if unit else FieldStatus.MISSING)
        self.reference = Field(
            raw=reference, status=FieldStatus.VERIFIED if reference else FieldStatus.MISSING
        )
        self.qualitative = None
        self.value_kind = ValueKind.NUMERIC
        self.status = FieldStatus.VERIFIED
        self.page = 0


def baseline_results(page_payload: dict, page_number: int) -> list[BaselineResult]:
    document = document_from_dict(
        {
            "report_id": page_payload["report_id"],
            "source_filename": "",
            "page_count": 1,
            "pages": [page_payload],
        }
    )
    page = document.pages[0]
    tables = build_page_tables(page_number, page.lines, page.width_pt, page.height_pt)
    out: list[BaselineResult] = []
    for block in tables.blocks:
        for row in block.rows:
            tokens = [w.text for w in row.all_words]
            numeric_index = next((i for i, t in enumerate(tokens) if looks_numeric(t)), None)
            if numeric_index is None or numeric_index == 0:
                continue
            test = " ".join(tokens[:numeric_index])
            value = tokens[numeric_index]
            unit = None
            reference = None
            for token in tokens[numeric_index + 1 :]:
                if unit is None and vocab.match_unit(token).canonical:
                    unit = token
                elif parse_reference(token).parsed_confidence > 0:
                    reference = token
            out.append(BaselineResult(test, value, unit, reference))
    return out


def main() -> int:
    gt = load_ground_truth(Path(__file__).resolve().parents[1] / "data" / "result_ground_truth")
    outcomes = []
    for path in sorted(Path(ARTIFACTS_DIR / "extractions").glob("*.extraction.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["report_id"] not in {rid for rid, _ in gt}:
            continue
        for page_payload in payload["pages"]:
            key = (payload["report_id"], page_payload["page_number"])
            if key not in gt or not page_payload.get("lines"):
                continue
            results = baseline_results(page_payload, page_payload["page_number"])
            outcomes.append(
                evaluate_page(key[0], key[1], gt[key]["rows"], results)
            )

    stats = aggregate(outcomes).to_dict()
    print(
        f"baseline rows matched={stats['matched']}/{stats['gt_rows']} "
        f"P={stats['row_precision']:.3f} R={stats['row_recall']:.3f}"
    )
    for name, field in stats["fields"].items():
        print(f"  {name:11s} accuracy={field['accuracy']} n={field['total_scored']}")
    print(
        f"  verified_wrong={stats['wrong_fields_marked_verified']} "
        f"wrong_assignment={stats['wrong_assignment_errors']} "
        f"decimal_corruption={stats['decimal_corruption_errors']}"
    )
    out = EVAL_DIR / "baseline_results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
