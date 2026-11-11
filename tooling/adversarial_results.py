#!/usr/bin/env python
"""Adversarial evaluation: does the system flag corruption instead of verifying it?

Real OCR evaluation on laboratory tables is impossible with this corpus (it has
no scanned table). What *can* be measured is the safety property that matters:
when the input is corrupted the way OCR corrupts it, does MediRead keep the
corrupted value out of ``verified``?

Method: take a real extraction artefact, apply one deterministic corruption to
its text, run the structured pipeline, and compare field-by-field against the
clean run on the same page. A corrupted field that stays ``verified`` is a
silent failure; a corrupted field that becomes ``uncertain`` / ``requires_review``
/ ``invalid`` is the system working.

Corruptions are synthetic and clearly labelled as such; they are not a substitute
for evaluating on real scans.

Usage:
    python tooling/adversarial_results.py
    python tooling/adversarial_results.py --out eval/adversarial.json
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mediread.config import ARTIFACTS_DIR, EVAL_DIR  # noqa: E402
from mediread.structured.pipeline import StructuredExtractionPipeline  # noqa: E402

PAGES = {
    "4f16a4444054fdfe": [3, 4, 5, 7, 8, 9, 10, 11],
    "c66749371af7e28c": [3, 7, 10],
    "0bd1dd6697b0d070": [2, 5, 6, 9, 10],
    "ac536c89c61f178c": [3],
}


def _mutate_words(page: dict, mutate) -> int:
    changed = 0
    for line in page.get("lines", []):
        for word in line.get("words", []):
            new = mutate(word["text"])
            if new != word["text"]:
                word["text"] = new
                changed += 1
        # keep the line text loosely consistent with its words
        if line.get("words"):
            line["text"] = " ".join(w["text"] for w in line["words"])
    return changed


def set_ocr_provenance(page: dict, confidence: float) -> int:
    """Mark all words as OCR output with a given confidence."""
    count = 0
    for line in page.get("lines", []):
        line["origin"] = "ocr"
        for word in line.get("words", []):
            word["confidence"] = confidence
            count += 1
    return count


def corrupt_micro(page: dict) -> int:
    """Apple Vision confuses the micro sign with H: µL -> HL, µIU -> HIU."""
    return _mutate_words(page, lambda t: t.replace("µ", "H").replace("μ", "H"))


def corrupt_decimal(page: dict) -> int:
    """Drop a decimal point: 65.63 -> 6563 (the classic silent corruption)."""
    def mutate(token: str) -> str:
        if re.fullmatch(r"\d+\.\d+", token):
            return token.replace(".", "")
        return token
    return _mutate_words(page, mutate)


def corrupt_digit(page: dict) -> int:
    """Change one digit, keeping the string length and decimal position."""
    rng = random.Random(7)

    def mutate(token: str) -> str:
        if not re.fullmatch(r"\d+(?:\.\d+)?", token) or len(token) < 1:
            return token
        positions = [i for i, ch in enumerate(token) if ch.isdigit() and ch != "."]
        index = rng.choice(positions)
        replacement = str((int(token[index]) + 1) % 10)
        return token[:index] + replacement + token[index + 1 :]
    return _mutate_words(page, mutate)


def corrupt_unit_merge(page: dict) -> int:
    """Merge the unit cell into the value cell by moving its words left."""
    changed = 0
    for tag in page.get("_ops", []):
        pass
    return changed


CORRUPTIONS = {
    "embedded/micro_as_H": (corrupt_micro, None),
    "embedded/decimal_dropped": (corrupt_decimal, None),
    "embedded/digit_changed": (corrupt_digit, None),
    "ocr/micro_as_H": (corrupt_micro, 0.98),
    "ocr/decimal_dropped": (corrupt_decimal, 0.98),
    "ocr/digit_changed": (corrupt_digit, 0.98),
}


def _field_key(result) -> str:
    return (result.test.raw or "").strip().lower()


def _comparable(result) -> dict:
    return {
        "value": result.value.raw,
        "unit": result.unit.raw,
        "reference": result.reference.raw,
        "status": result.status.value,
        "value_status": result.value.status.value,
        "unit_status": result.unit.status.value,
    }


def run_corruption(name: str, mutate, ocr_confidence, pipeline, extractions: dict[str, dict]) -> dict:
    stats = {
        "corruption": name,
        "pages": 0,
        "results_clean": 0,
        "corrupted_fields": 0,
        "flagged_corrupted_fields": 0,
        "flagged_by_validation": 0,
        "flagged_by_policy": 0,
        "undetected": 0,
        "verified_corrupted_fields": 0,
        "status_changed": 0,
        "examples": [],
    }
    for report_id, pages in PAGES.items():
        payload = copy.deepcopy(extractions[report_id])
        clean_doc = pipeline.process(copy.deepcopy(payload))
        clean_by_page: dict[int, dict[str, object]] = {}
        for result in clean_doc.results:
            clean_by_page.setdefault(result.page, {})[_field_key(result)] = result

        for page in payload["pages"]:
            if page["page_number"] in pages:
                if ocr_confidence is not None:
                    set_ocr_provenance(page, ocr_confidence)
                mutate(page)

        dirty_doc = pipeline.process(payload)
        for result in dirty_doc.results:
            key = _field_key(result)
            clean = clean_by_page.get(result.page, {}).get(key)
            if clean is None:
                continue
            stats["results_clean"] += 1
            before, after = _comparable(clean), _comparable(result)
            changed_fields = [
                field for field in ("value", "unit", "reference")
                if before[field] != after[field]
            ]
            if not changed_fields:
                continue
            stats["status_changed"] += int(before["status"] != after["status"])
            for field in changed_fields:
                stats["corrupted_fields"] += 1
                status = after[f"{field}_status"] if field != "reference" else (
                    result.reference.status.value
                )
                reasons = " ".join(
                    getattr(result, field).reasons if field != "reference" else result.reference.reasons
                )
                if status == "verified":
                    stats["verified_corrupted_fields"] += 1
                    stats["undetected"] += 1
                    if len(stats["examples"]) < 12:
                        stats["examples"].append(
                            {
                                "page": result.page,
                                "test": result.test.raw,
                                "field": field,
                                "clean": before[field],
                                "corrupted": after[field],
                                "status": status,
                                "failure": "undetected: corrupted field stayed verified",
                            }
                        )
                else:
                    stats["flagged_corrupted_fields"] += 1
                    # Distinguish *validation* (a rule noticed something wrong)
                    # from *policy* (OCR-derived fields are never auto-verified).
                    mechanism = "policy" if "OCR-derived" in reasons else "validation"
                    stats[f"flagged_by_{mechanism}"] += 1
                    if len(stats["examples"]) < 12:
                        stats["examples"].append(
                            {
                                "page": result.page,
                                "test": result.test.raw,
                                "field": field,
                                "clean": before[field],
                                "corrupted": after[field],
                                "status": status,
                                "mechanism": mechanism,
                            }
                        )
        stats["pages"] += len(pages)
    total = stats["corrupted_fields"]
    stats["detection_rate"] = (
        round(stats["flagged_corrupted_fields"] / total, 4) if total else None
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractions", default=str(ARTIFACTS_DIR / "extractions"))
    parser.add_argument("--out", default=str(EVAL_DIR / "adversarial.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    extractions = {}
    for report_id in PAGES:
        path = Path(args.extractions) / f"{report_id}.extraction.json"
        if not path.exists():
            raise SystemExit(f"missing extraction: {path}")
        extractions[report_id] = json.loads(path.read_text(encoding="utf-8"))

    pipeline = StructuredExtractionPipeline()
    results = []
    for name, (mutate, ocr_confidence) in CORRUPTIONS.items():
        stats = run_corruption(name, mutate, ocr_confidence, pipeline, extractions)
        results.append(stats)
        total = stats["corrupted_fields"]
        rate = stats["detection_rate"]
        print(
            f"{name:26s} corrupted={total:>3} validated={stats['flagged_by_validation']:>3} "
            f"policy={stats['flagged_by_policy']:>3} undetected={stats['undetected']:>3} "
            f"detection={rate}"
        )
        if args.verbose:
            for example in stats["examples"]:
                mark = "FAIL " if example.get("failure") else "ok   "
                print(
                    f"   {mark}p{example['page']} {example['test'][:26]:26s} {example['field']:9s} "
                    f"{str(example['clean'])[:18]:18s} -> {str(example['corrupted'])[:18]:18s} "
                    f"[{example['status']}/{example.get('mechanism', '-')}]"
                )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"corruptions": results}, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
