#!/usr/bin/env python
"""Build the representative evaluation subset and its provenance manifest.

The subset is the seven ground-truth pages. For each page the manifest records:

* the source report id, file name and page number;
* the **input class**, one of
    - ``digital_pdf``           — originals, selectable text
    - ``rendered_from_digital`` — our own 300 DPI render of a digital page
    - ``genuine_raster``        — a raster that was embedded in the report itself
    - ``camera_photo``          — none in this corpus
* the raster mode, DPI and pixel size actually used for scoring;
* the ground-truth file and how it was produced.

Images are written only with ``--write-images`` because a full-page render
contains patient metadata. The manifest itself contains no patient text.

Usage:
    python tooling/build_eval_set.py
    python tooling/build_eval_set.py --write-images
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pymupdf  # noqa: E402

from mediread.config import DATA_DIR, RAW_DIR  # noqa: E402
from mediread.evaluation.groundtruth import load_all_ground_truth  # noqa: E402
from mediread.ingest.inspect import open_pdf  # noqa: E402
from mediread.ingest.render import rasterise_page, render_page, save_raster  # noqa: E402

EVAL_SET_DIR = DATA_DIR / "evaluation_set"


def report_map() -> dict[str, str]:
    inventory = json.loads((DATA_DIR / "inventory" / "dataset_inventory.json").read_text())
    return {r["report_id"]: r["source_filename"] for r in inventory["reports"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-images", action="store_true", help="also write the rasters (local only)")
    args = parser.parse_args()

    EVAL_SET_DIR.mkdir(parents=True, exist_ok=True)
    files = report_map()
    entries = []
    for gt in load_all_ground_truth():
        filename = files[gt.report_id]
        path = RAW_DIR / filename
        doc = open_pdf(path)
        try:
            page = doc[gt.page_number - 1]
            if gt.source == "hand_transcription":
                raster = rasterise_page(doc, gt.page_number)
                input_class = "genuine_raster"
                note = "raster embedded in the report; OCR scored on native pixels"
            else:
                raster = render_page(page, dpi=300)
                input_class = "rendered_from_digital"
                note = "digital page rendered by MediRead at 300 DPI; not a scan"
            entry = {
                "report_id": gt.report_id,
                "source_filename": filename,
                "page_number": gt.page_number,
                "input_class": input_class,
                "camera_photo": False,
                "raster_source": raster.source,
                "raster_mode": raster.mode,
                "dpi": raster.dpi,
                "pixels": [raster.width_px, raster.height_px],
                "page_pt": [round(page.rect.width, 1), round(page.rect.height, 1)],
                "ground_truth_file": f"data/ground_truth/{gt.report_id}_p{gt.page_number:03d}.json",
                "ground_truth_source": gt.source,
                "ground_truth_provenance": gt.provenance,
                "ground_truth_rows": len(gt.lines),
                "note": note,
            }
            if args.write_images:
                suffix = "_scan" if input_class == "genuine_raster" else "_render300"
                out = save_raster(raster, gt.report_id, gt.page_number, suffix=suffix, root=EVAL_SET_DIR)
                entry["image_file"] = str(out.relative_to(DATA_DIR.parent))
                entry["image_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
            entries.append(entry)
        finally:
            doc.close()

    manifest = {
        "description": "Representative OCR evaluation subset for MediRead",
        "corpus": {
            "unique_reports": 10,
            "pages": 66,
            "genuine_scanned_tables": 0,
            "camera_photographs": 0,
        },
        "classes_present": sorted({e["input_class"] for e in entries}),
        "entries": sorted(entries, key=lambda e: (e["report_id"], e["page_number"])),
    }
    path = EVAL_SET_DIR / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {path} ({len(entries)} pages)")
    for entry in manifest["entries"]:
        print(f"  {entry['report_id'][:8]} p{entry['page_number']:>2} {entry['input_class']:22s} "
              f"{entry['pixels'][0]}x{entry['pixels'][1]} @{entry['dpi']}dpi rows={entry['ground_truth_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
