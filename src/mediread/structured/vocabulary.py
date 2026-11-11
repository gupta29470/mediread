"""Maintained vocabularies: units, qualitative results, test names, sections.

Design rules
------------
* **Units are matched exactly** after a well-defined character normalisation
  (case, micro sign, superscripts, spaces). An exact match can be ``verified``.
* **OCR confusions are never auto-resolved.** ``HL`` might be ``µL``; ``HIU/ML``
  might be ``µIU/mL``. Those produce a candidate plus ``uncertain`` status, never
  a silent replacement.
* **Test names are not fuzzy-merged.** Different tests with similar names
  (``BILIRUBIN - TOTAL`` / ``BILIRUBIN -DIRECT`` / ``BILIRUBIN (INDIRECT)``)
  must stay distinct. Normalisation is exact-alias only; similarity produces a
  *suggestion* that lowers confidence, never a merge.
* The vocabularies are data, not logic: extending them is adding entries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

# --------------------------------------------------------------------------
# Units
# --------------------------------------------------------------------------

_MICRO = {"\u00b5": "u", "\u03bc": "u"}  # micro sign, Greek mu
_SUPERSCRIPT = {"³": "3", "²": "2", "¹": "1"}
_WS = re.compile(r"\s+")


def normalise_unit(raw: str) -> str:
    """Normalise a unit string for *matching only*. The raw string is preserved."""
    text = raw.strip().lower()
    for source, target in {**_MICRO, **_SUPERSCRIPT, "×": "x", "^": "", "\u00a0": " "}.items():
        text = text.replace(source, target)
    # Keep "." — it is meaningful in "mL/min/1.73 m2". Trailing dots are stripped.
    text = _WS.sub("", text).rstrip(".")
    text = text.strip("*†‡")
    return text


class UnitStatus(str, Enum):
    EXACT = "exact"
    VARIANT = "variant"
    AMBIGUOUS = "ambiguous"
    UNKNOWN = "unknown"
    NONE = "none"          # explicit "no unit" placeholder such as "-" or "N/A"


@dataclass
class UnitMatch:
    canonical: str | None
    status: UnitStatus
    reason: str = ""
    alternatives: list[str] | None = None


# canonical -> display form
CANONICAL_UNITS: dict[str, str] = {
    "g/dl": "g/dL",
    "mg/dl": "mg/dL",
    "mg/l": "mg/L",
    "ug/dl": "µg/dL",
    "ug/ml": "µg/mL",
    "ug/l": "µg/L",
    "ng/ml": "ng/mL",
    "ng/dl": "ng/dL",
    "pg/ml": "pg/mL",
    "pg": "pg",
    "fl": "fL",
    "u/l": "U/L",
    "iu/l": "IU/L",
    "u/ml": "U/mL",
    "iu/ml": "IU/mL",
    "mmol/l": "mmol/L",
    "umol/l": "µmol/L",
    "meq/l": "mEq/L",
    "mol/l": "mol/L",
    "miu/l": "mIU/L",
    "uiu/ml": "µIU/mL",
    "miu/ml": "mIU/mL",
    "103/ul": "10^3/µL",
    "106/ul": "10^6/µL",
    "cells/hpf": "cells/HPF",
    "cells/lpf": "cells/LPF",
    "cells/ul": "cells/µL",
    "/hpf": "/HPF",
    "ml/min/1.73m2": "mL/min/1.73 m²",
    "ml/min": "mL/min",
    "mm/hr": "mm/hr",
    "sec": "sec",
    "seconds": "Seconds",
    "ratio": "Ratio",
    "index": "Index",
    "ml": "mL",
    "ul": "µL",
    "l": "L",
    "mosm/kg": "mOsm/kg",
    "mmhg": "mmHg",
    "percent": "%",
    "%": "%",
    "kpa": "kPa",
    "iu": "IU",
    "u": "U",
    "kg": "kg",
    "cm": "cm",
    "mm": "mm",
    "g": "g",
}

# Explicit variants that are not derivable by normalisation alone.
UNIT_VARIANTS: dict[str, str] = {
    "gm/dl": "g/dl",
    "gm/l": "g/l",
    "g/l": "g/l",
    "mg%": "mg/dl",          # legacy Indian notation: mg% == mg/dL
    "mgs/dl": "mg/dl",
    "mmol": "mmol/l",
    "meq": "meq/l",
    "cells/hpf*": "cells/hpf",
    "x103/ul": "103/ul",
    "x106/ul": "106/ul",
    "103/ul*": "103/ul",
    "mm/hr.": "mm/hr",
}

# No-unit placeholders seen in reports (urine strips, qualitative tests).
NO_UNIT_MARKERS = {"-", "--", "---", "n/a", "na", "none", "nil", ""}
_NO_UNIT_PATTERN = re.compile(r"^(?:[-–—_]\s*){1,4}$")

# Observed OCR confusions. These are *candidates*, never assertions.
OCR_UNIT_CONFUSIONS: dict[str, list[str]] = {
    "hl": ["ul"],
    "hiu/ml": ["uiu/ml"],
    "hg/dl": ["ug/dl"],
    "q/dl": ["g/dl"],
    "qm/dl": ["g/dl"],
    "mg/ul": ["mg/dl"],
    "pq": ["pg"],
    "rnmol/l": ["mmol/l"],
    "mmoi/l": ["mmol/l"],
}


def match_unit(raw: str | None) -> UnitMatch:
    """Classify a unit string without ever rewriting it."""
    if raw is None or not raw.strip():
        return UnitMatch(None, UnitStatus.UNKNOWN, "empty unit cell")
    text = raw.strip()
    if text.lower() in NO_UNIT_MARKERS or _NO_UNIT_PATTERN.match(text):
        return UnitMatch(None, UnitStatus.NONE, "explicit no-unit marker")

    key = normalise_unit(text)
    if key in UNIT_VARIANTS:
        return UnitMatch(CANONICAL_UNITS.get(UNIT_VARIANTS[key], UNIT_VARIANTS[key]), UnitStatus.VARIANT,
                         "known unit variant")
    if key in CANONICAL_UNITS:
        return UnitMatch(CANONICAL_UNITS[key], UnitStatus.EXACT, "known unit")

    # Compound forms such as "X 10³ / µL" normalise to "x103/ul" or "103/ul".
    if key.startswith("x") and key[1:] in CANONICAL_UNITS:
        return UnitMatch(CANONICAL_UNITS[key[1:]], UnitStatus.EXACT, "multiplier prefix")
    if re.fullmatch(r"10\^?[369]/ul", key) or re.fullmatch(r"[0-9]+/ul", key):
        exponent = re.sub(r"[^0-9]", "", key)[:1]
        canonical = CANONICAL_UNITS.get(f"10{exponent}/ul")
        if canonical:
            return UnitMatch(canonical, UnitStatus.VARIANT, "count-per-volume form")

    if key in OCR_UNIT_CONFUSIONS:
        candidates = [CANONICAL_UNITS.get(c, c) for c in OCR_UNIT_CONFUSIONS[key]]
        return UnitMatch(
            None,
            UnitStatus.AMBIGUOUS,
            f"'{text}' is not a valid unit; it resembles {', '.join(candidates)} "
            "(possible OCR confusion)",
            candidates,
        )

    # Unknown but unit-shaped: report it as unknown rather than guessing.
    if "/" in key or key.isalpha():
        return UnitMatch(None, UnitStatus.UNKNOWN, f"unit '{text}' not in vocabulary")
    return UnitMatch(None, UnitStatus.UNKNOWN, f"unrecognised unit text '{text}'")


# --------------------------------------------------------------------------
# Qualitative results
# --------------------------------------------------------------------------

QUALITATIVE_CANONICAL: dict[str, str] = {
    "positive": "Positive",
    "pos": "Positive",
    "reactive": "Reactive",
    "negative": "Negative",
    "neg": "Negative",
    "non reactive": "Non-reactive",
    "no agglutination": "No Agglutination",
    "agglutination": "Agglutination",
    "nonreactive": "Non-reactive",
    "non-reactive": "Non-reactive",
    "detected": "Detected",
    "not detected": "Not Detected",
    "notdetected": "Not Detected",
    "absent": "Absent",
    "present": "Present",
    "trace": "Trace",
    "normal": "Normal",
    "abnormal": "Abnormal",
    "clear": "Clear",
    "slight cloudy": "Slight Cloudy",
    "cloudy": "Cloudy",
    "turbid": "Turbid",
    "pale yellow": "Pale Yellow",
    "yellow": "Yellow",
    "amber": "Amber",
    "straw": "Straw",
    "colourless": "Colourless",
    "colorless": "Colourless",
    "nil": "Nil",
    "few": "Few",
    "many": "Many",
    "occasional": "Occasional",
    "bdl": "Below Detection Limit",
    "below detection limit": "Below Detection Limit",
}

# Tests whose qualitative vocabulary is a closed, test-specific set. Single
# letters are otherwise dangerous (noise), but a blood group is exactly one
# letter and must not be forced into a number or rejected.
QUALITATIVE_BY_TEST: dict[str, set[str]] = {
    "blood_grouping": {"A", "B", "AB", "O"},
    "rh_typing": {"POSITIVE", "NEGATIVE"},
}

QUALITATIVE_PATTERNS = [
    re.compile(r"^not\s+detected$", re.I),
    re.compile(r"^non[\s-]?reactive$", re.I),
    re.compile(r"^(positive|negative)$", re.I),
    re.compile(r"^\+\+?$"),
    re.compile(r"^(1\+|2\+|3\+)$"),
]

# Words that look like values but are methodology or column labels.
METHOD_WORDS = {
    "photometry", "calculated", "h.p.l.c", "hplc", "c.m.i.a", "cmia",
    "i.s.e", "ise", "immunoassay", "immunoturbidimetry", "agglutination",
    "westergren", "titration", "microscopy", "fluoride", "photometric",
    "colorimetric", "electrode", "chemiluminescence", "clia", "elisa",
    "nephelometry", "turbidimetry", "hplc", "capillary",
}

COLUMN_LABELS = {
    "test", "test name", "testname", "investigation", "parameter", "tests",
    "technology", "method", "value", "values", "result", "results",
    "observation", "observations", "units", "unit", "reference", "range",
    "ref", "interval", "bio. ref. interval.", "bio ref interval",
    "reference range", "ref. range", "normal range", "bio. ref. interval",
    "ref range", "reference interval",
}


def match_qualitative(raw: str) -> str | None:
    """Return a canonical qualitative label, or None if it is not one."""
    text = _WS.sub(" ", raw.strip().lower())
    if text in QUALITATIVE_CANONICAL:
        return QUALITATIVE_CANONICAL[text]
    for pattern in QUALITATIVE_PATTERNS:
        if pattern.match(text):
            return raw.strip().title()
    return None


# --------------------------------------------------------------------------
# Tests and sections
# --------------------------------------------------------------------------

class Section(str, Enum):
    HEMOGRAM = "CBC / Hemogram"
    LIVER = "Liver function"
    KIDNEY = "Kidney function"
    ELECTROLYTES = "Electrolytes"
    LIPID = "Lipid profile"
    THYROID = "Thyroid profile"
    DIABETES = "Glucose and HbA1c"
    URINE = "Urine analysis"
    COAGULATION = "Coagulation (PT/INR)"
    VITAMINS = "Vitamins and minerals"
    IRON = "Iron studies"
    INFLAMMATION = "Inflammation markers"
    ELECTROPHORESIS = "Haemoglobin electrophoresis"
    OTHER = "Other"


@dataclass(frozen=True)
class TestEntry:
    test_id: str
    display: str
    section: Section
    expected_units: tuple[str, ...] = ()


# Canonical tests seen in the corpus plus common equivalents. Aliases are exact
# after normalisation (case, punctuation and spacing collapsed).
TEST_ENTRIES: tuple[TestEntry, ...] = (
    # Hemogram
    TestEntry("hemoglobin", "Haemoglobin", Section.HEMOGRAM, ("g/dl",)),
    TestEntry("total_leucocyte_count", "Total leucocyte count (WBC)", Section.HEMOGRAM, ("103/ul",)),
    TestEntry("neutrophils", "Neutrophils", Section.HEMOGRAM, ("%",)),
    TestEntry("lymphocytes", "Lymphocytes", Section.HEMOGRAM, ("%",)),
    TestEntry("monocytes", "Monocytes", Section.HEMOGRAM, ("%",)),
    TestEntry("eosinophils", "Eosinophils", Section.HEMOGRAM, ("%",)),
    TestEntry("basophils", "Basophils", Section.HEMOGRAM, ("%",)),
    TestEntry("platelet_count", "Platelet count", Section.HEMOGRAM, ("103/ul",)),
    TestEntry("total_rbc", "Total RBC", Section.HEMOGRAM, ("106/ul",)),
    TestEntry("hematocrit", "Haematocrit (PCV)", Section.HEMOGRAM, ("%",)),
    TestEntry("mcv", "MCV", Section.HEMOGRAM, ("fl",)),
    TestEntry("mch", "MCH", Section.HEMOGRAM, ("pg",)),
    TestEntry("mchc", "MCHC", Section.HEMOGRAM, ("g/dl",)),
    TestEntry("rdw_sd", "RDW-SD", Section.HEMOGRAM, ("fl",)),
    TestEntry("rdw_cv", "RDW-CV", Section.HEMOGRAM, ("%",)),
    # Liver
    TestEntry("alkaline_phosphatase", "Alkaline phosphatase", Section.LIVER, ("u/l",)),
    TestEntry("bilirubin_total", "Bilirubin total", Section.LIVER, ("mg/dl",)),
    TestEntry("bilirubin_direct", "Bilirubin direct", Section.LIVER, ("mg/dl",)),
    TestEntry("bilirubin_indirect", "Bilirubin indirect", Section.LIVER, ("mg/dl",)),
    TestEntry("ggt", "GGT", Section.LIVER, ("u/l",)),
    TestEntry("sgot", "SGOT (AST)", Section.LIVER, ("u/l",)),
    TestEntry("sgpt", "SGPT (ALT)", Section.LIVER, ("u/l",)),
    TestEntry("sgot_sgpt_ratio", "SGOT/SGPT ratio", Section.LIVER, ("ratio",)),
    TestEntry("total_protein", "Total protein", Section.LIVER, ("g/dl",)),
    TestEntry("albumin", "Albumin", Section.LIVER, ("g/dl",)),
    TestEntry("globulin", "Globulin", Section.LIVER, ("g/dl",)),
    TestEntry("albumin_globulin_ratio", "Albumin/globulin ratio", Section.LIVER, ("ratio",)),
    # Kidney
    TestEntry("blood_urea_nitrogen", "Blood urea nitrogen (BUN)", Section.KIDNEY, ("mg/dl",)),
    TestEntry("creatinine", "Creatinine (serum)", Section.KIDNEY, ("mg/dl",)),
    TestEntry("bun_creatinine_ratio", "BUN/creatinine ratio", Section.KIDNEY, ("ratio",)),
    TestEntry("urea", "Urea", Section.KIDNEY, ("mg/dl",)),
    TestEntry("uric_acid", "Uric acid", Section.KIDNEY, ("mg/dl",)),
    TestEntry("egfr", "Estimated GFR (eGFR)", Section.KIDNEY, ("ml/min/1.73m2",)),
    # Electrolytes
    TestEntry("sodium", "Sodium", Section.ELECTROLYTES, ("mmol/l",)),
    TestEntry("potassium", "Potassium", Section.ELECTROLYTES, ("mmol/l",)),
    TestEntry("chloride", "Chloride", Section.ELECTROLYTES, ("mmol/l",)),
    TestEntry("calcium", "Calcium", Section.ELECTROLYTES, ("mg/dl",)),
    TestEntry("phosphorus", "Phosphorus", Section.ELECTROLYTES, ("mg/dl",)),
    # Lipids
    TestEntry("total_cholesterol", "Total cholesterol", Section.LIPID, ("mg/dl",)),
    TestEntry("triglycerides", "Triglycerides", Section.LIPID, ("mg/dl",)),
    TestEntry("hdl_cholesterol", "HDL cholesterol", Section.LIPID, ("mg/dl",)),
    TestEntry("ldl_cholesterol", "LDL cholesterol", Section.LIPID, ("mg/dl",)),
    TestEntry("vldl_cholesterol", "VLDL cholesterol", Section.LIPID, ("mg/dl",)),
    TestEntry("ldl_hdl_ratio", "LDL/HDL ratio", Section.LIPID, ("ratio",)),
    TestEntry("hdl_ldl_ratio", "HDL/LDL ratio", Section.LIPID, ("ratio",)),
    TestEntry("non_hdl_cholesterol", "Non-HDL cholesterol", Section.LIPID, ("mg/dl",)),
    TestEntry("total_cholesterol_hdl_ratio", "Total cholesterol/HDL ratio", Section.LIPID, ("ratio",)),
    # Thyroid
    TestEntry("t3", "Total T3", Section.THYROID, ("ng/dl",)),
    TestEntry("t4", "Total T4", Section.THYROID, ("ug/dl",)),
    TestEntry("tsh", "TSH", Section.THYROID, ("uiu/ml",)),
    # Diabetes
    TestEntry("hba1c", "HbA1c", Section.DIABETES, ("%",)),
    TestEntry("average_blood_glucose", "Average blood glucose", Section.DIABETES, ("mg/dl",)),
    TestEntry("fasting_glucose", "Fasting blood glucose", Section.DIABETES, ("mg/dl",)),
    # Coagulation
    TestEntry("prothrombin_time", "Prothrombin time", Section.COAGULATION, ("sec",)),
    TestEntry("inr", "INR", Section.COAGULATION, ("ratio",)),
    # Vitamins / iron / inflammation
    TestEntry("vitamin_d", "25-OH Vitamin D", Section.VITAMINS, ("ng/ml",)),
    TestEntry("vitamin_b12", "Vitamin B12", Section.VITAMINS, ("pg/ml",)),
    TestEntry("iron", "Iron", Section.IRON, ("ug/dl",)),
    TestEntry("ferritin", "Ferritin", Section.IRON, ("ng/ml",)),
    TestEntry("tibc", "Total iron binding capacity", Section.IRON, ("ug/dl",)),
    TestEntry("esr", "ESR", Section.INFLAMMATION, ("mm/hr",)),
    TestEntry("crp", "C-reactive protein", Section.INFLAMMATION, ("mg/l",)),
    # Electrophoresis
    TestEntry("hb_a", "Hb A", Section.ELECTROPHORESIS, ("%",)),
    TestEntry("hb_a2", "Hb A2", Section.ELECTROPHORESIS, ("%",)),
    TestEntry("hb_f", "Hb F", Section.ELECTROPHORESIS, ("%",)),
    TestEntry("hb_c", "Hb C", Section.ELECTROPHORESIS, ("%",)),
    TestEntry("hb_d", "Hb D", Section.ELECTROPHORESIS, ("%",)),
    TestEntry("hb_s", "Hb S", Section.ELECTROPHORESIS, ("%",)),
    # Urine
    TestEntry("blood_grouping", "Blood group", Section.OTHER),
    TestEntry("rh_typing", "Rh typing", Section.OTHER),
    TestEntry("urine_volume", "Volume", Section.URINE, ("ml",)),
    TestEntry("urine_colour", "Colour", Section.URINE),
    TestEntry("urine_appearance", "Appearance", Section.URINE),
    TestEntry("urine_ph", "pH", Section.URINE),
    TestEntry("specific_gravity", "Specific gravity", Section.URINE),
    TestEntry("urine_protein", "Urinary protein", Section.URINE),
    TestEntry("urine_glucose", "Urinary glucose", Section.URINE),
    TestEntry("urine_ketone", "Urine ketone", Section.URINE),
    TestEntry("urine_bilirubin", "Urinary bilirubin", Section.URINE),
    TestEntry("urobilinogen", "Urobilinogen", Section.URINE),
    TestEntry("urine_blood", "Urine blood", Section.URINE),
    TestEntry("nitrite", "Nitrite", Section.URINE),
    TestEntry("leucocyte_esterase", "Leucocyte esterase", Section.URINE),
    TestEntry("pus_cells", "Urinary leucocytes (pus cells)", Section.URINE, ("cells/hpf",)),
    TestEntry("red_blood_cells_urine", "Red blood cells (urine)", Section.URINE, ("cells/hpf",)),
    TestEntry("epithelial_cells", "Epithelial cells", Section.URINE, ("cells/hpf",)),
)

_ALIASES: dict[str, str] = {
    # normalized alias -> test_id
    "haemoglobin": "hemoglobin",
    "hemoglobin": "hemoglobin",
    "hb": "hemoglobin",
    "hgb": "hemoglobin",
    "total leucocytes count wbc": "total_leucocyte_count",
    "total leucocyte count": "total_leucocyte_count",
    "total leucocytes count": "total_leucocyte_count",
    "wbc": "total_leucocyte_count",
    "platelet count": "platelet_count",
    "platelets": "platelet_count",
    "total rbc": "total_rbc",
    "rbc": "total_rbc",
    "blood grouping": "blood_grouping",
    "blood group": "blood_grouping",
    "rh typing": "rh_typing",
    "rh factor": "rh_typing",
    "haematocrit pcv": "hematocrit",
    "hematocrit pcv": "hematocrit",
    "hematocrit": "hematocrit",
    "haematocrit": "hematocrit",
    "pcv": "hematocrit",
    "mean corpuscular volume mcv": "mcv",
    "mean corpuscular volume": "mcv",
    "mean corpuscular hemoglobin": "mch",
    "mean corp hemo conc": "mchc",
    "mean corpuscular hemoglobin mch": "mch",
    "mean corp hemo conc mchc": "mchc",
    "alkaline phosphatase": "alkaline_phosphatase",
    "alp": "alkaline_phosphatase",
    "bilirubin total": "bilirubin_total",
    "bilirubin direct": "bilirubin_direct",
    "bilirubin indirect": "bilirubin_indirect",
    "gamma glutamyl transferase ggt": "ggt",
    "ggt": "ggt",
    "aspartate aminotransferase sgot": "sgot",
    "sgot": "sgot",
    "ast": "sgot",
    "alanine transaminase sgpt": "sgpt",
    "sgpt": "sgpt",
    "alt": "sgpt",
    "sgot sgpt ratio": "sgot_sgpt_ratio",
    "protein total": "total_protein",
    "total protein": "total_protein",
    "albumin serum": "albumin",
    "albumin": "albumin",
    "serum globulin": "globulin",
    "globulin": "globulin",
    "serum alb globulin ratio": "albumin_globulin_ratio",
    "albumin globulin ratio": "albumin_globulin_ratio",
    "blood urea nitrogen bun": "blood_urea_nitrogen",
    "bun": "blood_urea_nitrogen",
    "creatinine serum": "creatinine",
    "creatinine": "creatinine",
    "bun sr creatinine ratio": "bun_creatinine_ratio",
    "urea calculated": "urea",
    "urea": "urea",
    "uric acid": "uric_acid",
    "est glomerular filtration rate egfr": "egfr",
    "egfr": "egfr",
    "sodium": "sodium",
    "potassium": "potassium",
    "chloride": "chloride",
    "calcium": "calcium",
    "phosphorous": "phosphorus",
    "phosphorus": "phosphorus",
    "total cholesterol": "total_cholesterol",
    "triglycerides": "triglycerides",
    "hdl cholesterol": "hdl_cholesterol",
    "ldl cholesterol": "ldl_cholesterol",
    "vldl cholesterol": "vldl_cholesterol",
    "ldl hdl ratio": "ldl_hdl_ratio",
    "hdl ldl ratio": "hdl_ldl_ratio",
    "non hdl cholesterol": "non_hdl_cholesterol",
    "hemoglobin a2": "hb_a2",
    "haemoglobin a2": "hb_a2",
    "hemoglobin a": "hb_a",
    "hemoglobin f": "hb_f",
    "hemoglobin c": "hb_c",
    "hemoglobin d": "hb_d",
    "hemoglobin s": "hb_s",
    "total triiodothyronine t3": "t3",
    "t3": "t3",
    "total thyroxine t4": "t4",
    "t4": "t4",
    "tsh ultrasensitive": "tsh",
    "tsh": "tsh",
    "hba1c hplc": "hba1c",
    "hba1c": "hba1c",
    "average blood glucose abg": "average_blood_glucose",
    "prothrombin time": "prothrombin_time",
    "international normalized ratio": "inr",
    "inr": "inr",
    "25 oh vitamin d total": "vitamin_d",
    "vitamin d": "vitamin_d",
    "iron": "iron",
    "erythrocyte sedimentation rate esr": "esr",
    "esr": "esr",
}

TEST_ID_TO_ENTRY = {entry.test_id: entry for entry in TEST_ENTRIES}


def normalise_test_name(raw: str) -> str:
    """Case/punctuation-insensitive key for alias lookup (not for display)."""
    text = raw.lower()
    text = text.replace("(", " ").replace(")", " ").replace("-", " ").replace("/", " ")
    text = text.replace(".", " ").replace("_", " ").replace(",", " ")
    return _WS.sub(" ", text).strip()


def lookup_test(raw: str) -> tuple[str | None, TestEntry | None]:
    """Exact-alias lookup. Returns (test_id, entry) or (None, None)."""
    key = normalise_test_name(raw)
    test_id = _ALIASES.get(key)
    if test_id is None:
        return None, None
    return test_id, TEST_ID_TO_ENTRY.get(test_id)


def _ratio(a: str, b: str) -> float:
    """Character-bigram Dice coefficient; used only for suggestions."""
    if not a or not b:
        return 0.0
    a = a.replace(" ", "")
    b = b.replace(" ", "")
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    from collections import Counter

    bigrams_a = Counter(a[i : i + 2] for i in range(len(a) - 1))
    bigrams_b = Counter(b[i : i + 2] for i in range(len(b) - 1))
    overlap = sum((bigrams_a & bigrams_b).values())
    return 2.0 * overlap / (sum(bigrams_a.values()) + sum(bigrams_b.values()))


def suggest_test(raw: str, threshold: float = 0.86) -> tuple[str | None, float]:
    """Best fuzzy suggestion for an unknown test name.

    Returns a *suggestion* only. Callers must not treat it as an identification:
    similar names such as ``BILIRUBIN - TOTAL`` and ``BILIRUBIN -DIRECT`` are
    deliberately distinct tests and must not be merged.
    """
    key = normalise_test_name(raw)
    best_id, best_score = None, 0.0
    for alias, test_id in _ALIASES.items():
        score = _ratio(key, alias)
        if score > best_score:
            best_id, best_score = test_id, score
    if best_score >= threshold:
        return best_id, best_score
    return None, best_score


SECTION_KEYWORDS: dict[Section, tuple[str, ...]] = {
    Section.URINE: ("urine", "urinogram", "physical examination", "chemical examination",
                    "microscopic examination", "specific gravity", "urobilinogen"),
    Section.HEMOGRAM: ("leucocyte", "hemoglobin", "haemoglobin", "platelet", "neutrophil",
                       "lymphocyte", "monocyte", "eosinophil", "basophil", "rbc", "mcv",
                       "mch", "hematocrit", "haematocrit", "rdw"),
    Section.LIVER: ("bilirubin", "transaminase", "sgot", "sgpt", "albumin", "globulin",
                    "phosphatase", "ggt", "protein - total", "prothrombin"),
    Section.KIDNEY: ("creatinine", "urea", "egfr", "glomerular", "uric acid", "bun"),
    Section.ELECTROLYTES: ("sodium", "potassium", "chloride", "calcium", "phosphor"),
    Section.LIPID: ("cholesterol", "triglyceride", "hdl", "ldl", "vldl"),
    Section.THYROID: ("triiodothyronine", "thyroxine", "tsh", "thyroid", "t3", "t4"),
    Section.DIABETES: ("hba1c", "glucose", "glycated", "blood sugar"),
    Section.COAGULATION: ("prothrombin", "inr", "aptt", "coagulation"),
    Section.VITAMINS: ("vitamin", "b12", "folate"),
    Section.IRON: ("iron", "ferritin", "tibc", "transferrin"),
    Section.INFLAMMATION: ("esr", "sedimentation", "c-reactive", "crp"),
    Section.ELECTROPHORESIS: ("electrophoresis", "hb a", "hb a2", "hb f"),
}


def section_for_test(raw: str) -> Section:
    """Section inferred from a test name when no section heading is present."""
    lowered = raw.lower()
    for section, keywords in SECTION_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lowered:
                return section
    return Section.OTHER


@dataclass
class TestMatch:
    test_id: str | None
    entry: TestEntry | None
    exact: bool
    suggestion: str | None
    suggestion_score: float


def match_test(raw: str) -> TestMatch:
    test_id, entry = lookup_test(raw)
    if test_id:
        return TestMatch(test_id, entry, True, None, 1.0)
    suggestion, score = suggest_test(raw)
    return TestMatch(None, None, False, suggestion, score)
