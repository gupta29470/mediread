"""Evaluate the app's OCR pipeline against the digital text of the same pages.

Inputs are produced on the device by the debug import path (lines_dump.txt) and
by PyMuPDF for the digital ground truth. Nothing here feeds back into the app;
the app never sees this script.

    .venv/bin/python tooling/evaluate_app_ocr.py \
        --digital-pdf "medical reports/7a5e102c31d63afe80340d8a8e296dc7.pdf" \
        --digital-rows .cache/shots/device_dump4.txt \
        --ocr-dump .cache/eval/scanned_dump3.txt \
        --pages 3 7 11 \
        --out .cache/eval/ocr_eval.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf


def norm(text: str) -> str:
    text = text.lower().replace(",", " ").replace("/", " ")
    text = re.sub(r"[^a-z0-9.<>%µ ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in norm(text).split(" ") if t]


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    reference = norm(reference)
    hypothesis = norm(hypothesis)
    return edit_distance(reference, hypothesis) / max(1, len(reference))


def wer_bag(reference: str, hypothesis: str) -> float:
    """Order-insensitive WER: recognition quality without reading-order effects.

    A scan and a text layer can order blocks differently (side-by-side address
    and table columns), which inflates a sequence WER without any recognition
    error. Comparing sorted word bags measures the words themselves.
    """
    ref = sorted(tokens(reference))
    hyp = sorted(tokens(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(" ".join(ref), " ".join(hyp)) / len(ref)


def wer(reference: str, hypothesis: str) -> float:
    ref = tokens(reference)
    hyp = tokens(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(" ".join(ref), " ".join(hyp)) / len(ref)


def parse_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    text = path.read_text(errors="replace")
    if "===== rows" not in text:
        return rows
    section = text.split("===== rows", 1)[1]
    for line in section.splitlines():
        if line.startswith("====="):
            break
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        page = re.search(r"page=(\d+)", parts[5])
        rows.append({
            "name": parts[0],
            "value": parts[1],
            "unit": parts[2],
            "reference": parts[3],
            "stratified": "strat=true" in parts[4],
            "page": int(page.group(1)) if page else None,
        })
    return rows


def parse_ocr_dump(path: Path) -> dict:
    text = path.read_text(errors="replace")
    pages, rows, tokens_out, renders = [], [], [], []
    section = None
    for line in text.splitlines():
        if line.startswith("===== "):
            section = line[len("===== "):].split(" ")[0]
            continue
        if section == "pages" and "|" in line:
            parts = line.split("|")
            if len(parts) >= 8 and parts[0].isdigit():
                pages.append({
                    "page": int(parts[0]), "kind": parts[1],
                    "embedded_chars": int(parts[2]), "ocr_words": int(parts[3]),
                    "added_words": int(parts[4]), "dropped_words": int(parts[5]),
                    "render_ms": int(parts[6]), "ocr_ms": int(parts[7]),
                })
        elif section == "ocr_tokens" and "|" in line:
            parts = line.split("|")
            if len(parts) == 6 and parts[0].isdigit():
                tokens_out.append({
                    "page": int(parts[0]), "text": parts[1],
                    "left": float(parts[2]), "top": float(parts[3]),
                    "right": float(parts[4]), "bottom": float(parts[5]),
                })
            elif parts[0] == "render":
                match = re.search(r"px=(\d+)x(\d+)", parts[2])
                ppp = re.search(r"ppp=([\d.]+)", line)
                if match and ppp:
                    renders.append({
                        "page": int(parts[1]), "px": int(match.group(1)),
                        "py": int(match.group(2)), "ppp": float(ppp.group(1)),
                    })
    rows = parse_rows(path)
    return {"pages": pages, "rows": rows, "tokens": tokens_out, "renders": renders}


def iou(a: dict, b: dict) -> float:
    left = max(a["left"], b["left"])
    right = min(a["right"], b["right"])
    top = max(a["top"], b["top"])
    bottom = min(a["bottom"], b["bottom"])
    if right <= left or bottom <= top:
        return 0.0
    inter = (right - left) * (bottom - top)
    area_a = (a["right"] - a["left"]) * (a["bottom"] - a["top"])
    area_b = (b["right"] - b["left"]) * (b["bottom"] - b["top"])
    return inter / (area_a + area_b - inter)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digital-pdf", type=Path, required=True)
    parser.add_argument("--digital-rows", type=Path, required=True)
    parser.add_argument("--ocr-dump", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", required=True,
                        help="digital page numbers, in scanned-document order")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    digital_rows = [r for r in parse_rows(args.digital_rows) if r["page"] in args.pages]
    ocr = parse_ocr_dump(args.ocr_dump)
    ocr_rows = ocr["rows"]

    page_map = {index + 1: page for index, page in enumerate(args.pages)}
    by_name = {norm(r["name"]): r for r in digital_rows}
    matched = []
    for row in ocr_rows:
        digital = by_name.get(norm(row["name"]))
        if digital is None:
            continue
        matched.append((digital, row))

    def exact(a: str | None, b: str | None) -> bool:
        return norm(a or "") == norm(b or "")

    value_ok = sum(1 for d, o in matched if exact(d["value"], o["value"]))
    unit_ok = sum(1 for d, o in matched if exact(d["unit"], o["unit"]))
    range_ok = sum(1 for d, o in matched if exact(d["reference"], o["reference"]))
    decimals = [(d, o) for d, o in matched if "." in (d["value"] or "")]
    decimal_ok = sum(1 for d, o in decimals if exact(d["value"], o["value"]))

    document = pymupdf.open(args.digital_pdf)
    renders = {r["page"]: r for r in ocr["renders"]}
    per_page = []
    for scanned_page, digital_page in page_map.items():
        page = document[digital_page - 1]
        reference = page.get_text("text")
        page_tokens = [t for t in ocr["tokens"] if t["page"] == scanned_page]
        hypothesis = " ".join(t["text"] for t in page_tokens)
        scale = renders.get(scanned_page, {}).get("ppp", 1.0)
        words = [
            {
                "text": w[4], "left": w[0], "top": w[1], "right": w[2], "bottom": w[3],
            }
            for w in page.get_text("words")
        ]
        by_text: dict[str, list[dict]] = {}
        for word in words:
            by_text.setdefault(norm(word["text"]), []).append(word)
        ious = []
        for token in page_tokens:
            box = {
                "left": token["left"] * scale, "top": token["top"] * scale,
                "right": token["right"] * scale, "bottom": token["bottom"] * scale,
            }
            candidates = by_text.get(norm(token["text"]))
            if not candidates:
                continue
            ious.append(max(iou(box, c) for c in candidates))
        seen = {}
        duplicates = 0
        for token in page_tokens:
            key = (norm(token["text"]), round(token["left"]), round(token["top"]))
            duplicates += 1 if key in seen else 0
            seen[key] = True
        outcome = next((p for p in ocr["pages"] if p["page"] == scanned_page), {})
        per_page.append({
            "scanned_page": scanned_page,
            "digital_page": digital_page,
            "kind": outcome.get("kind"),
            "ocr_words": len(page_tokens),
            "cer": round(cer(reference, hypothesis), 4),
            "wer": round(wer(reference, hypothesis), 4),
            "wer_bag": round(wer_bag(reference, hypothesis), 4),
            "bbox_matched": len(ious),
            "bbox_mean_iou": round(sum(ious) / len(ious), 4) if ious else None,
            "duplicate_rate": round(duplicates / max(1, len(page_tokens)), 4),
            "render_ms": outcome.get("render_ms"),
            "ocr_ms": outcome.get("ocr_ms"),
        })

    total_ms = sum((p.get("render_ms") or 0) + (p.get("ocr_ms") or 0) for p in ocr["pages"])
    report = {
        "pages": per_page,
        "rows": {
            "digital": len(digital_rows),
            "ocr": len(ocr_rows),
            "matched": len(matched),
            "recall": round(len(matched) / max(1, len(digital_rows)), 4),
            "value_exact": round(value_ok / max(1, len(matched)), 4),
            "unit_exact": round(unit_ok / max(1, len(matched)), 4),
            "range_exact": round(range_ok / max(1, len(matched)), 4),
            "decimal_exact": round(decimal_ok / max(1, len(decimals)), 4) if decimals else None,
            "decimal_rows": len(decimals),
        },
        "timing": {
            "pages": len(ocr["pages"]),
            "total_ms": total_ms,
            "mean_page_ms": round(total_ms / max(1, len(ocr["pages"])), 1),
        },
        "unmatched_ocr_rows": [r["name"] for r in ocr_rows if norm(r["name"]) not in by_name],
        "missing_rows": [d["name"] for d in digital_rows if norm(d["name"]) not in
                         {norm(r["name"]) for r in ocr_rows}],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
