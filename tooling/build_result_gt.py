#!/usr/bin/env python
"""Manually verified ground truth for structured laboratory results.

Authoring method
----------------
Every row below was transcribed from the **page itself**: the verbatim cell text
of the embedded PDF layer (which is the producing system's own string, not OCR
output) and checked against the 300 DPI rendered page. Rows were re-verified by
viewing the rendered table region during curation; discrepancies found during
evaluation are fixed here, never in the parser.

Rules used while annotating
---------------------------
* ``value`` is the exact printed token, including a leading ``<``/``>`` when the
  laboratory printed a bound instead of a measurement.
* ``unit`` is the exact printed unit text; ``"-"`` means the report prints a
  no-unit marker.
* ``reference`` is the exact printed reference text. Stratified band tables
  (HbA1c ADA guidance, eGFR ranges) are marked ``reference_kind="stratified"``
  and excluded from exact-match scoring, because they are not a single interval.
* Qualitative results are recorded as ``kind="qualitative"`` with the printed
  text; they are never converted to numbers.
* Patient identifiers are not part of any row and never enter this file.

Run ``python tooling/build_result_gt.py`` to (re)write the JSON files.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "result_ground_truth"


def row(test, value, unit, reference, *, kind="numeric", reference_kind="numeric", qualitative=None):
    return {
        "test": test,
        "value": value,
        "unit": unit,
        "reference": reference,
        "kind": kind,
        "reference_kind": reference_kind,
        "qualitative": qualitative,
    }


# --------------------------------------------------------------------------
# Annotations
# --------------------------------------------------------------------------

PAGES = {
    # ---- 0d3182cc (12-page comprehensive report) -------------------------
    ("4f16a4444054fdfe", 3): [
        row("VOLUME", "3", "mL", "-", kind="numeric"),
        row("COLOUR", "PALE YELLOW", "-", "Pale Yellow", kind="qualitative", reference_kind="qualitative", qualitative="Pale Yellow"),
        row("APPEARANCE", "SLIGHT CLOUDY", "-", "Clear", kind="qualitative", reference_kind="qualitative", qualitative="Slight Cloudy"),
        row("SPECIFIC GRAVITY", "< 1.003", "-", "1.003-1.030", kind="bound"),
        row("PH", "5", "-", "5-8"),
        row("URINARY PROTEIN", "ABSENT", "mg/dL", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("URINARY GLUCOSE", "ABSENT", "mg/dL", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("URINE KETONE", "ABSENT", "mg/dL", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("URINARY BILIRUBIN", "ABSENT", "mg/dL", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("UROBILINOGEN", "Normal", "mg/dL", "<=0.2", kind="qualitative", reference_kind="numeric", qualitative="Normal"),
        row("BILE SALT", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("BILE PIGMENT", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("URINE BLOOD", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("NITRITE", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("LEUCOCYTE ESTERASE", "PRESENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Present"),
        row("MUCUS", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("RED BLOOD CELLS", "ABSENT", "cells/HPF", "0-5", kind="qualitative", reference_kind="numeric", qualitative="Absent"),
        row("URINARY LEUCOCYTES (PUS CELLS)", "8", "cells/HPF", "0-5"),
        row("EPITHELIAL CELLS", "5", "cells/HPF", "0-5"),
        row("CASTS", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("CRYSTALS", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("BACTERIA", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("YEAST", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
        row("PARASITE", "ABSENT", "-", "Absent", kind="qualitative", reference_kind="qualitative", qualitative="Absent"),
    ],
    ("4f16a4444054fdfe", 4): [
        row("PROTHROMBIN TIME", "11.2", "Seconds", "9.8-12.1 Seconds"),
        row("INTERNATIONAL NORMALIZED RATIO", "0.9", "Ratio", "0.90-1.10"),
    ],
    ("4f16a4444054fdfe", 5): [
        row("ALKALINE PHOSPHATASE", "65.63", "U/L", "45-129"),
        row("BILIRUBIN - TOTAL", "0.58", "mg/dL", "0.3-1.2"),
        row("BILIRUBIN -DIRECT", "0.13", "mg/dL", "< 0.3"),
        row("BILIRUBIN (INDIRECT)", "0.45", "mg/dL", "0-0.9"),
        row("GAMMA GLUTAMYL TRANSFERASE (GGT)", "13.83", "U/L", "< 38"),
        row("ASPARTATE AMINOTRANSFERASE (SGOT )", "33.1", "U/L", "< 31"),
        row("ALANINE TRANSAMINASE (SGPT)", "22.53", "U/L", "< 34"),
        row("SGOT / SGPT RATIO", "1.47", "Ratio", "< 2"),
        row("PROTEIN - TOTAL", "6.41", "gm/dL", "5.7-8.2"),
        row("ALBUMIN - SERUM", "3.79", "gm/dL", "3.2-4.8"),
        row("SERUM GLOBULIN", "2.62", "gm/dL", "2.5-3.4"),
        row("SERUM ALB/GLOBULIN RATIO", "1.45", "Ratio", "0.9 - 2"),
    ],
    ("4f16a4444054fdfe", 7): [
        row("SODIUM", "136.17", "mmol/L", "Adults: 136-145 mmol/l"),
        row("POTASSIUM", "4.3", "mmol/L", "ADULTS: 3.5-5.1 MMOL/L"),
        row("CHLORIDE", "103.54", "mmol/L", "ADULTS: 98-107 MMOL/L"),
    ],
    ("4f16a4444054fdfe", 8): [
        row("BLOOD UREA NITROGEN (BUN)", "6.45", "mg/dL", "7.94 - 20.07"),
        row("CREATININE - SERUM", "0.52", "mg/dL", "0.55-1.02"),
        row("BUN / SR.CREATININE RATIO", "12.4", "Ratio", "9:1-23:1", reference_kind="ratio"),
        row("UREA (CALCULATED)", "13.8", "mg/dL", "Adult : 17-43"),
        row("UREA / SR.CREATININE RATIO", "26.54", "Ratio", "< 52"),
        row("CALCIUM", "9.19", "mg/dL", "8.8-10.6"),
        row("URIC ACID", "4.4", "mg/dL", "3.2 - 6.1"),
    ],
    ("4f16a4444054fdfe", 9): [
        row("EST. GLOMERULAR FILTRATION RATE (eGFR)", "112", "mL/min/1.73 m2", None,
            reference_kind="stratified"),
    ],
    ("4f16a4444054fdfe", 10): [
        row("HbA1c - (HPLC)", "5.3", "%", None, reference_kind="stratified"),
        row("AVERAGE BLOOD GLUCOSE (ABG)", "105", "mg/dL", None, reference_kind="stratified"),
    ],
    ("4f16a4444054fdfe", 11): [
        row("TOTAL LEUCOCYTES COUNT (WBC)", "6.02", "X 10³ / µL", "4.0 - 10.0"),
        row("NEUTROPHILS", "63.6", "%", "40-80"),
        row("LYMPHOCYTE", "28.4", "%", "20-40"),
        row("MONOCYTES", "3", "%", "2-10"),
        row("EOSINOPHILS", "4.2", "%", "1-6"),
        row("BASOPHILS", "0.5", "%", "0-2"),
        row("IMMATURE GRANULOCYTE PERCENTAGE(IG%)", "0.3", "%", "0.0-0.4"),
        row("NEUTROPHILS - ABSOLUTE COUNT", "3.82", "X 10³ / µL", "2.0-7.0"),
        row("LYMPHOCYTES - ABSOLUTE COUNT", "1.71", "X 10³ / µL", "1.0-3.0"),
        row("MONOCYTES - ABSOLUTE COUNT", "0.18", "X 10³ / µL", "0.2 - 1.0"),
        row("BASOPHILS - ABSOLUTE COUNT", "0.03", "X 10³ / µL", "0.02 - 0.1"),
        row("EOSINOPHILS - ABSOLUTE COUNT", "0.25", "X 10³ / µL", "0.02 - 0.5"),
        row("IMMATURE GRANULOCYTES(IG)", "0.03", "X 10³ / µL", "0.0-0.3"),
        row("TOTAL RBC", "4.39", "X 10^6/µL", "3.8-4.8"),
        row("NUCLEATED RED BLOOD CELLS", "0.01", "X 10³ / µL", "0.0-0.5"),
        row("NUCLEATED RED BLOOD CELLS %", "0.01", "%", "0.0-5.0"),
        row("HEMOGLOBIN", "9.2", "g/dL", "12.0-15.0"),
        row("HEMATOCRIT(PCV)", "32", "%", "36.0-46.0"),
        row("MEAN CORPUSCULAR VOLUME(MCV)", "72.9", "fL", "83.0-101.0"),
        row("MEAN CORPUSCULAR HEMOGLOBIN(MCH)", "21", "pq", "27.0-32.0"),
        row("MEAN CORP.HEMO.CONC(MCHC)", "28.8", "g/dL", "31.5-34.5"),
        row("RED CELL DISTRIBUTION WIDTH - SD(RDW-SD)", "42.6", "fL", "39.0-46.0"),
        row("RED CELL DISTRIBUTION WIDTH (RDW-CV)", "16.3", "%", "11.6-14.0"),
        row("PLATELET COUNT", "264", "X 10³ / µL", "150-410"),
    ],
    # ---- 7a5e102c (16-page report, second patient) ------------------------
    ("c66749371af7e28c", 7): [
        row("TOTAL CHOLESTEROL", "113", "mg/dL", "< 200"),
        row("HDL CHOLESTEROL - DIRECT", "39", "mg/dL", "40-60"),
        row("LDL CHOLESTEROL - DIRECT", "73", "mg/dL", "< 100"),
        row("TRIGLYCERIDES", "64", "mg/dL", "< 150"),
        row("VLDL CHOLESTEROL", "12.72", "mg/dL", "5 - 40"),
        row("HDL / LDL RATIO", "0.53", "Ratio", "> 0.40"),
        row("LDL / HDL RATIO", "1.9", "Ratio", "1.5-3.5"),
        row("TC/ HDL CHOLESTEROL RATIO", "2.9", "Ratio", "3 - 5"),
        row("TRIG / HDL RATIO", "1.63", "Ratio", "< 3.12"),
        row("NON-HDL CHOLESTEROL", "73.9", "mg/dL", "< 160"),
    ],
    ("c66749371af7e28c", 10): [
        row("TOTAL TRIIODOTHYRONINE (T3)", "70", "ng/dL", "58-159"),
        row("TOTAL THYROXINE (T4)", "4.42", "µg/dL", "4.87-11.72"),
        row("TSH - ULTRASENSITIVE", "3.82", "µIU/mL", "0.35-4.94"),
    ],
    ("c66749371af7e28c", 3): [
        row("CA-125", "29.7", "U/mL", "Less than 30.2 U/ml", reference_kind="qualitative"),
    ],
    # ---- 98ccaa82 (3-page beta-thalassaemia screen) -----------------------
    ("ac536c89c61f178c", 3): [
        row("HEMOGLOBIN A2", "4.5", "%", "ADULT : 2.1 - 3.5"),
        row("HEMOGLOBIN F", "0.3", "%", "ADULT : < 2"),
        row("HEMOGLOBIN C", "Not Detected", "-", "--", kind="qualitative", reference_kind="none", qualitative="Not Detected"),
        row("HEMOGLOBIN D", "Not Detected", "-", "--", kind="qualitative", reference_kind="none", qualitative="Not Detected"),
        row("HEMOGLOBIN S", "Not Detected", "-", "--", kind="qualitative", reference_kind="none", qualitative="Not Detected"),
    ],
    # ---- 4bc2a93c (single page, different producer) ----------------------
    ("79bd8cfc0570272b", 1): [
        row("Hb A", "95.9", None, None, reference_kind="none"),
        row("Hb A2", "4.1", None, None, reference_kind="none"),
    ],
}

# --------------------------------------------------------------------------
# Holdout annotations — pages never inspected while developing the parser.
# Annotated after the parser reached its development score. They contain rows
# the development set does not: "Nil" results, a free-text result ("Calcium
# Oxalate Crystals"), a urine strip with PRESENT, the "Reference Range :" label
# wording, and PDW/MPV tests seen nowhere else.
# --------------------------------------------------------------------------

HOLDOUT_PAGES = {
    ("0bd1dd6697b0d070", 2): [
        row("TOTAL LEUCOCYTES COUNT", "6.69", "X 10³ / µL", "4.0-10.0"),
        row("NEUTROPHILS", "65.7", "%", "40-80"),
        row("LYMPHOCYTE PERCENTAGE", "28", "%", "20.0-40.0"),
        row("MONOCYTES", "3.3", "%", "0.0-10.0"),
        row("EOSINOPHILS", "2.1", "%", "0.0-6.0"),
        row("BASOPHILS", "0.6", "%", "<2"),
        row("IMMATURE GRANULOCYTE PERCENTAGE(IG%)", "0.3", "%", "0.0-0.4"),
        row("NEUTROPHILS - ABSOLUTE COUNT", "4.4", "X 10³ / µL", "2.0-7.0"),
        row("LYMPHOCYTES - ABSOLUTE COUNT", "1.87", "X 10³ / µL", "1.0-3.0"),
        row("MONOCYTES - ABSOLUTE COUNT", "0.22", "X 10³ / µL", "0.2-1.0"),
        row("BASOPHILS - ABSOLUTE COUNT", "0.04", "X 10³ / µL", "0.02-0.1"),
        row("EOSINOPHILS - ABSOLUTE COUNT", "0.14", "X 10³ / µL", "0.02-0.5"),
        row("IMMATURE GRANULOCYTES(IG)", "0.02", "X 10³ / µL", "0.0-0.3"),
        row("TOTAL RBC", "4.05", "X 10^6/µL", "3.9-4.8"),
        row("NUCLEATED RED BLOOD CELLS", "Nil", "X 10³ / µL", "<0.01", kind="qualitative",
            reference_kind="numeric", qualitative="Nil"),
        row("NUCLEATED RED BLOOD CELLS %", "Nil", "%", "<0.01", kind="qualitative",
            reference_kind="numeric", qualitative="Nil"),
        row("HEMOGLOBIN", "9", "g/dL", "12.0-15.0"),
        row("HEMATOCRIT(PCV)", "31.3", "%", "36.0-46.0"),
        row("MEAN CORPUSCULAR VOLUME(MCV)", "77.3", "fL", "83.0-101.0"),
        row("MEAN CORPUSCULAR HEMOGLOBIN(MCH)", "22.2", "pq", "27.0-32.0"),
        row("MEAN CORP.HEMO.CONC(MCHC)", "28.8", "g/dL", "31.5-34.5"),
        row("RED CELL DISTRIBUTION WIDTH - SD(RDW-SD)", "45.1", "fL", "39.0-46.0"),
        row("RED CELL DISTRIBUTION WIDTH (RDW-CV)", "16.3", "%", "11.6-14.0"),
        row("PLATELET DISTRIBUTION WIDTH(PDW)", "19.8", "fL", "9.6-15.2"),
        row("MEAN PLATELET VOLUME(MPV)", "13", "fL", "6.5-12"),
        row("PLATELET COUNT", "260", "X 10³ / µL", "150-400"),
        row("PLATELET TO LARGE CELL RATIO(PLCR)", "49.6", "%", "19.7-42.4"),
        row("PLATELETCRIT(PCT)", "0.34", "%", "0.19-0.39"),
    ],
    ("0bd1dd6697b0d070", 6): [
        row("CHLORIDE", "102.1", "mmol/l", "Adults: 98-107 mmol/l"),
    ],
    ("0bd1dd6697b0d070", 9): [
        row("EST. GLOMERULAR FILTRATION RATE (eGFR)", "113", "mL/min/1.73 m2", None,
            reference_kind="stratified"),
    ],
    ("e07acc8ef3875b45", 11): [
        row("VOLUME", "3", "mL", "-"),
        row("COLOUR", "PALE YELLOW", "-", "Pale Yellow", kind="qualitative",
            reference_kind="qualitative", qualitative="Pale Yellow"),
        row("APPEARANCE", "CLEAR", "-", "Clear", kind="qualitative",
            reference_kind="qualitative", qualitative="Clear"),
        row("SPECIFIC GRAVITY", "1.02", "-", "1.003-1.030"),
        row("PH", "5.5", "-", "5-8"),
        row("URINARY PROTEIN", "ABSENT", "mg/dL", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("URINARY GLUCOSE", "ABSENT", "mg/dL", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("URINE KETONE", "ABSENT", "mg/dL", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("URINARY BILIRUBIN", "ABSENT", "mg/dL", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("UROBILINOGEN", "Normal", "mg/dL", "<=0.2", kind="qualitative",
            reference_kind="numeric", qualitative="Normal"),
        row("BILE SALT", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("BILE PIGMENT", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("URINE BLOOD", "PRESENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Present"),
        row("NITRITE", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("MICROALBUMIN", "10", "mg/L", "< 30"),
        row("MUCUS", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("RED BLOOD CELLS", "25", "cells/HPF", "0-5"),
        row("URINARY LEUCOCYTES (PUS CELLS)", "ABSENT", "cells/HPF", "0-5",
            kind="qualitative", reference_kind="numeric", qualitative="Absent"),
        row("EPITHELIAL CELLS", "5", "cells/HPF", "0-5"),
        row("CASTS", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("CRYSTALS", "CALCIUM OXALATE CRYSTALS", "-", "Absent", kind="text",
            reference_kind="qualitative"),
        row("BACTERIA", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("YEAST", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("PARASITE", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
    ],
}

# --------------------------------------------------------------------------
# Blind holdout — annotated from a report that was never opened while tuning.
# The parser is generic, but these pages were selected and transcribed only now;
# the first evaluation run on them is reported unchanged in docs/result_evaluation.md.
# --------------------------------------------------------------------------

BLIND_PAGES = {
    ("0bd1dd6697b0d070", 5): [
        row("BILIRUBIN -DIRECT", "0.18", "mg/dl", "< 0.3"),
        row("BILIRUBIN - TOTAL", "0.57", "mg/dl", "0.3-1.2"),
        row("BILIRUBIN (INDIRECT)", "0.39", "mg/dl", "0-0.9"),
        row("ASPARTATE AMINOTRANSFERASE (SGOT )", "28.9", "U/l", "< 31"),
        row("ALANINE TRANSAMINASE (SGPT)", "13.6", "U/l", "< 34"),
        row("ALKALINE PHOSPHATASE", "78.6", "U/L", "45 - 129"),
        row("GAMMA GLUTAMYL TRANSFERASE (GGT)", "12.6", "U/l", "< 38"),
        row("PROTEIN - TOTAL", "6.67", "gm/dl", "5.7-8.2"),
        row("ALBUMIN - SERUM", "3.82", "gm/dl", "3.2-4.8"),
        row("SERUM GLOBULIN", "2.85", "gm/dL", "2.5-3.4"),
        row("SERUM ALB/GLOBULIN RATIO", "1.34", "Ratio", "0.9 - 2"),
    ],
    ("0bd1dd6697b0d070", 10): [
        row("VOLUME", "3", "mL", "-"),
        row("COLOUR", "Straw", "-", "Pale Yellow", kind="qualitative",
            reference_kind="qualitative", qualitative="Straw"),
        row("APPEARANCE", "CLEAR", "-", "Clear", kind="qualitative",
            reference_kind="qualitative", qualitative="Clear"),
        row("SPECIFIC GRAVITY", "1.01", "-", "1.003-1.030"),
        row("PH", "5.5", "-", "5 - 8"),
        row("URINARY PROTEIN", "NEGATIVE", "mg/dl", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("URINARY GLUCOSE", "NEGATIVE", "mg/dl", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("URINE KETONE", "NEGATIVE", "mg/dl", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("URINARY BILIRUBIN", "NEGATIVE", "mg/dl", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("UROBILINOGEN", "< 0.2", "mg/dl", "<=0.2", kind="bound"),
        row("BILE SALT", "NEGATIVE", "-", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("BILE PIGMENT", "NEGATIVE", "-", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("URINE BLOOD", "NEGATIVE", "Cells/ul*", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("NITRITE", "NEGATIVE", "-", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("MICROALBUMIN", "10", "mg/l", "< 20"),
        row("MUCUS", "ABSENT", "mg/ul", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("RED BLOOD CELLS", "ABSENT", "Cells/ul*", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("URINARY LEUCOCYTES", "NEGATIVE", "Cells/ul*", "Negative", kind="qualitative",
            reference_kind="qualitative", qualitative="Negative"),
        row("EPITHELIAL CELLS", "1-2", "-", "2-3", kind="range"),
        row("CASTS", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("CRYSTALS", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("BACTERIA", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("YEAST", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
        row("PARASITE", "ABSENT", "-", "Absent", kind="qualitative",
            reference_kind="qualitative", qualitative="Absent"),
    ],
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for split, pages in (
        ("development", PAGES),
        ("holdout", HOLDOUT_PAGES),
        ("blind", BLIND_PAGES),
    ):
        for (report_id, page), rows in pages.items():
            payload = {
                "report_id": report_id,
                "page": page,
                "split": split,
                "source": "embedded_text_layer",
                "verified_by": "verbatim PDF cell text checked against a 300 DPI render",
                "rows": rows,
            }
            path = OUT_DIR / f"{report_id}_p{page:03d}.json"
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            total += len(rows)
            print(f"{path.name}: {len(rows)} rows [{split}]")
    print(f"{len(PAGES) + len(HOLDOUT_PAGES) + len(BLIND_PAGES)} pages, {total} annotated rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
