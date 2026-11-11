#!/usr/bin/env python
"""Dataset reconnaissance CLI.

Produces a structural inventory of every PDF in the corpus and a page-level
classification. Writes JSON + Markdown to ``data/inventory``. Text is never
written to disk; ``--preview`` prints redacted text to the console only.

Usage:
    python tooling/survey_dataset.py                 # inventory only
    python tooling/survey_dataset.py --preview       # + redacted page previews
    python tooling/survey_dataset.py --report <id>   # single report
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402

from mediread.config import INVENTORY_DIR, RAW_DIR  # noqa: E402
from mediread.ingest.inspect import document_profile, inspect_pdf, open_pdf  # noqa: E402
from mediread.privacy import redact_text  # noqa: E402


def collect(paths: list[Path]) -> tuple[list[dict], dict[str, list[str]]]:
    reports: list[dict] = []
    by_hash: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        stats = inspect_pdf(path)
        record = stats.to_dict()
        record["document_profile"] = document_profile(stats)
        record["duplicate_of"] = None
        by_hash[stats.sha256].append(path.name)
        reports.append(record)
    # Exactly one file per digest is canonical; every other member of the group
    # records which file it duplicates.
    for record in reports:
        group = sorted(by_hash[record["sha256"]])
        if len(group) > 1 and record["source_filename"] != group[0]:
            record["duplicate_of"] = group[0]
    return reports, by_hash


def markdown_table(reports: list[dict]) -> str:
    lines = [
        "| # | Report id | File | Pages | Profile | Page classes | Text chars | Image cover | Tables (H/V rules) |",
        "|---|-----------|------|-------|---------|--------------|-----------:|------------:|--------------------|",
    ]
    for index, report in enumerate(reports, 1):
        pages = report["pages"]
        classes = ", ".join(f"{k}:{v}" for k, v in sorted(report["page_classes"].items()))
        text_chars = sum(p["char_count"] for p in pages)
        img_cover = sum(p["image_area_ratio"] for p in pages) / max(1, len(pages))
        rules = sum(p["horizontal_rule_count"] for p in pages)
        vrules = sum(p["vertical_rule_count"] for p in pages)
        lines.append(
            f"| {index} | `{report['report_id']}` | `{report['source_filename']}` | "
            f"{report['page_count']} | {report['document_profile']} | {classes} | "
            f"{text_chars:,} | {img_cover:.0%} | {rules}/{vrules} |"
        )
    return "\n".join(lines)


def page_table(report: dict) -> str:
    lines = [
        "| Page | Size (pt) | Class | Chars | Words | Text cov | Img cov | Imgs | H/V rules | Suspicious | Reason |",
        "|-----:|-----------|-------|------:|------:|---------:|--------:|-----:|-----------|------------|--------|",
    ]
    for page in report["pages"]:
        lines.append(
            f"| {page['page_number']} | {page['width_pt']:.0f}x{page['height_pt']:.0f} | "
            f"{page['page_class']} | {page['char_count']} | {page['word_count']} | "
            f"{page['text_area_ratio']:.1%} | {page['image_area_ratio']:.1%} | "
            f"{page['image_count']} | {page['horizontal_rule_count']}/{page['vertical_rule_count']} | "
            f"{'yes' if page['suspicious_text'] else 'no'} | {page['page_class_reason']} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="print redacted text previews")
    parser.add_argument("--report", help="limit to one report id or filename fragment")
    parser.add_argument("--pages", help="page list for preview, e.g. 1,4-6")
    parser.add_argument("--chars", type=int, default=1200, help="preview characters per page")
    args = parser.parse_args()

    paths = sorted(RAW_DIR.glob("*.pdf"))
    if args.report:
        paths = [p for p in paths if args.report in p.name or args.report in p.stem[:16]]

    reports, by_hash = collect(paths)
    reports.sort(key=lambda r: (r["page_count"], r["source_filename"]))

    INVENTORY_DIR.mkdir(parents=True, exist_ok=True)
    # Only an unfiltered run defines the canonical inventory; ad-hoc runs must
    # not clobber it.
    if not args.report:
        payload = {
            "file_count": len(reports),
            "unique_documents": len(by_hash),
            "duplicate_groups": {k: v for k, v in by_hash.items() if len(v) > 1},
            "reports": reports,
        }
        (INVENTORY_DIR / "dataset_inventory.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    print(f"files inspected: {len(reports)}  unique sha256: {len(by_hash)}")
    if len(by_hash) < len(reports):
        print("duplicate groups:")
        for digest, names in by_hash.items():
            if len(names) > 1:
                print(f"  {digest[:12]} -> {names}")
    print()
    print(markdown_table(reports))

    for report in reports:
        if args.report is None and report.get("duplicate_of"):
            continue
        print(f"\n### {report['source_filename']} ({report['report_id']}) — {report['page_count']} pages")
        print(page_table(report))

    if args.preview:
        target = [r for r in reports if not r.get("duplicate_of")] if not args.report else reports
        for report in target:
            doc = open_pdf(RAW_DIR / report["source_filename"])
            try:
                wanted = _parse_pages(args.pages, doc.page_count)
                for number in wanted:
                    page = doc[number - 1]
                    text = page.get_text("text", sort=True) or ""
                    print(f"\n--- {report['source_filename']} p{number} "
                          f"({'EMPTY' if not text.strip() else f'{len(text)} chars'}) ---")
                    print(redact_text(text[: args.chars]))
            finally:
                doc.close()
    return 0


def _parse_pages(spec: str | None, page_count: int) -> list[int]:
    if not spec:
        return list(range(1, min(page_count, 3) + 1))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [p for p in out if 1 <= p <= page_count]


if __name__ == "__main__":
    raise SystemExit(main())
