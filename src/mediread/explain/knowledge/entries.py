"""Bundled knowledge catalogue: what each supported test measures.

Every entry is an original summary written from the approved sources in
:mod:`sources`. Nothing is copied verbatim; each ``measures``/``low_note``/
``high_note`` statement is traceable to the listed source ids.

``status``
    ``complete``  — the entry has an approved source for what the test measures
                    and for how results are usually described.
    ``partial``   — the test is named in an approved source but the source does
                    not describe it in detail. The engine still shows
                    ``measures`` when present but suppresses directional notes
                    and marks the education section as partial.

Tests with no entry are **unsupported**: the engine says so and does not invent
an explanation. Adding a test is a data change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeEntry:
    test_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    category: str
    kind: str                     # "numeric" | "qualitative"
    measures: str
    why_ordered: str
    general_note: str
    low_note: str | None
    high_note: str | None
    qualitative_note: str | None
    limitations: tuple[str, ...]
    sources: tuple[str, ...]
    status: str = "complete"


_COMMON_LIMITS = (
    "The reference interval printed on your report is specific to the laboratory "
    "that produced it; intervals from other laboratories are not interchangeable.",
    "A result outside the printed interval may or may not reflect a health problem, "
    "and a result inside the interval does not by itself guarantee health.",
)


def _e(
    test_id: str,
    canonical_name: str,
    aliases: tuple[str, ...],
    category: str,
    measures: str,
    why_ordered: str,
    general_note: str,
    sources: tuple[str, ...],
    *,
    kind: str = "numeric",
    low_note: str | None = None,
    high_note: str | None = None,
    qualitative_note: str | None = None,
    limitations: tuple[str, ...] = (),
    status: str = "complete",
) -> KnowledgeEntry:
    return KnowledgeEntry(
        test_id=test_id,
        canonical_name=canonical_name,
        aliases=aliases,
        category=category,
        kind=kind,
        measures=measures,
        why_ordered=why_ordered,
        general_note=general_note,
        low_note=low_note,
        high_note=high_note,
        qualitative_note=qualitative_note,
        limitations=_COMMON_LIMITS + limitations,
        sources=sources,
        status=status,
    )


ENTRIES: tuple[KnowledgeEntry, ...] = (
    # ---------------------------------------------------------------- CBC
    _e(
        "hemoglobin", "Haemoglobin", ("hemoglobin", "haemoglobin", "hb", "hgb"),
        "CBC / Hemogram",
        "Haemoglobin is the iron-rich protein inside red blood cells that carries "
        "oxygen from the lungs to the rest of the body.",
        "It is part of a complete blood count and is used to look for anaemia and to "
        "monitor conditions that affect red blood cells.",
        "The result is the amount of haemoglobin in a measured volume of blood, "
        "usually reported in grams per decilitre (g/dL).",
        ("mp_lab_cbc",),
        low_note="A haemoglobin result below the printed interval is commonly described "
                 "as low. MedlinePlus notes that abnormal red-cell, haemoglobin or "
                 "haematocrit levels may be a sign of dehydration, anaemia, heart "
                 "disease or too little iron, and that other factors can affect results.",
        high_note="A haemoglobin result above the printed interval is interpreted "
                  "together with the red-cell count, haematocrit and your clinical "
                  "context rather than on its own.",
        limitations=(
            "Haemoglobin can be affected by hydration and by factors such as diet, "
            "activity, medicines and menstruation (MedlinePlus).",
        ),
    ),
    _e(
        "total_leucocyte_count", "Total white blood cell count",
        ("total leucocytes count", "total leucocyte count", "total leucocytes count wbc",
         "white blood cell count", "wbc"),
        "CBC / Hemogram",
        "White blood cells are part of the immune system and help the body fight "
        "infection and other diseases; a complete blood count measures the total "
        "number in a volume of blood.",
        "It is used in routine checks and to monitor infections, immune conditions "
        "and treatments that affect blood cells.",
        "The result is the total number of white blood cells per volume of blood.",
        ("mp_lab_cbc", "mp_lab_differential"),
        low_note="A low total white-cell count is described by MedlinePlus as possibly "
                 "related to bone-marrow disease, chemotherapy, certain medicines, "
                 "cancer or HIV, among other causes.",
        high_note="A high total white-cell count is described by MedlinePlus as possibly "
                  "related to infection, autoimmune or inflammatory disorders, "
                  "leukaemia or other cancers, allergic reactions or certain steroids.",
        limitations=(
            "MedlinePlus notes that abnormal white-cell results do not always mean a "
            "condition that needs treatment; injury, stress, smoking and alcohol can "
            "also affect the count.",
        ),
    ),
    _e(
        "neutrophils", "Neutrophils", ("neutrophils", "neutrophil", "neutrophils absolute count"),
        "CBC / Hemogram",
        "Neutrophils are the most common type of white blood cell and the body's main "
        "defence when bacteria, viruses or other germs enter the body.",
        "They are reported as part of a white-cell differential, which can help "
        "investigate an infection or an immune condition.",
        "The result is usually a percentage of white cells or an absolute count.",
        ("mp_lab_differential",),
    ),
    _e(
        "lymphocytes", "Lymphocytes", ("lymphocytes", "lymphocyte", "lymphocyte percentage",
         "lymphocytes absolute count", "lymphocyte absolute count"),
        "CBC / Hemogram",
        "Lymphocytes are white blood cells that include B cells and T cells; B cells "
        "fight invading viruses, bacteria and toxins, and some T cells target infected "
        "or cancer cells.",
        "They are reported as part of a white-cell differential.",
        "The result is usually a percentage of white cells or an absolute count.",
        ("mp_lab_differential",),
    ),
    _e(
        "monocytes", "Monocytes", ("monocytes", "monocyte", "monocytes absolute count"),
        "CBC / Hemogram",
        "Monocytes are white blood cells that kill bacteria, viruses and other germs, "
        "support the immune response and clear away dead cells.",
        "They are reported as part of a white-cell differential.",
        "The result is usually a percentage of white cells or an absolute count.",
        ("mp_lab_differential",),
    ),
    _e(
        "eosinophils", "Eosinophils", ("eosinophils", "eosinophil", "eosinophils absolute count"),
        "CBC / Hemogram",
        "Eosinophils are white blood cells that defend against parasites and are "
        "involved in allergies and in controlling inflammation.",
        "They are reported as part of a white-cell differential.",
        "The result is usually a percentage of white cells or an absolute count.",
        ("mp_lab_differential",),
    ),
    _e(
        "basophils", "Basophils", ("basophils", "basophil", "basophils absolute count"),
        "CBC / Hemogram",
        "Basophils are white blood cells that release enzymes during allergic reactions "
        "and asthma attacks.",
        "They are reported as part of a white-cell differential.",
        "The result is usually a percentage of white cells or an absolute count.",
        ("mp_lab_differential",),
    ),
    _e(
        "platelet_count", "Platelet count", ("platelet count", "platelets"),
        "CBC / Hemogram",
        "Platelets are small cell fragments that stop bleeding by helping blood to clot.",
        "A platelet count is part of a complete blood count and is used to check "
        "bleeding and clotting.",
        "The result is the number of platelets per volume of blood.",
        ("mp_lab_cbc",),
    ),
    _e(
        "total_rbc", "Red blood cell count", ("total rbc", "red blood cell count", "rbc"),
        "CBC / Hemogram",
        "Red blood cells carry oxygen from the lungs to the rest of the body.",
        "A red-cell count is part of a complete blood count and helps assess anaemia "
        "and other blood conditions.",
        "The result is the number of red blood cells per volume of blood.",
        ("mp_lab_cbc",),
    ),
    _e(
        "hematocrit", "Haematocrit (PCV)",
        ("hematocrit", "haematocrit", "hematocrit pcv", "haematocrit pcv", "pcv"),
        "CBC / Hemogram",
        "Haematocrit is the amount of whole blood that is made up of red blood cells.",
        "It is part of a complete blood count and is interpreted together with "
        "haemoglobin and the red-cell count.",
        "The result is usually a percentage.",
        ("mp_lab_cbc",),
        limitations=(
            "Haematocrit can be affected by hydration, as with haemoglobin (MedlinePlus).",
        ),
    ),
    _e(
        "mcv", "Mean corpuscular volume (MCV)",
        ("mean corpuscular volume", "mean corpuscular volume mcv", "mcv"),
        "CBC / Hemogram",
        "MCV measures the average size of your red blood cells.",
        "It is one of the red-cell indices and helps clinicians classify types of anaemia.",
        "The result describes red-cell size, not the number of cells.",
        ("mp_lab_rbc_indices",),
        low_note="MedlinePlus describes smaller-than-usual red cells as possibly related "
                 "to iron-deficiency anaemia or thalassaemia, among other causes.",
        high_note="MedlinePlus describes larger-than-usual red cells as possibly related "
                  "to vitamin B deficiency or liver disease, among other causes.",
    ),
    _e(
        "mch", "Mean corpuscular haemoglobin (MCH)",
        ("mean corpuscular hemoglobin", "mean corpuscular haemoglobin",
         "mean corpuscular hemoglobin mch", "mch"),
        "CBC / Hemogram",
        "MCH measures the average amount of haemoglobin in a single red blood cell.",
        "It is one of the red-cell indices used to classify anaemia.",
        "The result describes haemoglobin content per cell.",
        ("mp_lab_rbc_indices",),
        low_note="MedlinePlus describes a lower-than-usual MCH as possibly related to "
                 "iron-deficiency anaemia.",
        high_note="MedlinePlus describes a higher-than-usual MCH as possibly related to "
                  "anaemia from vitamin B deficiency.",
    ),
    _e(
        "mchc", "Mean corpuscular haemoglobin concentration (MCHC)",
        ("mean corp hemo conc", "mean corp hemo conc mchc", "mchc"),
        "CBC / Hemogram",
        "MCHC describes how concentrated haemoglobin is within your red blood cells.",
        "It is one of the red-cell indices used to classify anaemia.",
        "The result describes haemoglobin concentration, not the total amount of "
        "haemoglobin in the blood.",
        ("mp_lab_rbc_indices",),
        low_note="MedlinePlus describes a lower-than-usual MCHC as possibly related to "
                 "iron-deficiency anaemia or thalassaemia.",
        high_note="MedlinePlus describes a higher-than-usual MCHC as possibly related to "
                  "haemolytic anaemia or hereditary spherocytosis.",
    ),
    _e(
        "rdw_cv", "Red cell distribution width (RDW-CV)",
        ("red cell distribution width rdw cv", "rdw cv", "rdw"),
        "CBC / Hemogram",
        "RDW measures differences in the size of your red blood cells; healthy red "
        "cells are usually about the same size.",
        "It is part of a complete blood count and is usually interpreted with the "
        "other red-cell indices.",
        "A higher RDW indicates more variation in red-cell size.",
        ("mp_lab_rbc_indices",),
        limitations=(
            "MedlinePlus notes that RDW alone is not enough to make a diagnosis and is "
            "combined with other results.",
        ),
    ),
    _e(
        "rdw_sd", "Red cell distribution width (RDW-SD)",
        ("red cell distribution width sd rdw sd",),
        "CBC / Hemogram",
        "RDW-SD is one way of expressing variation in the size of red blood cells.",
        "It is part of a complete blood count and is interpreted with other red-cell "
        "indices.",
        "Higher values indicate more variation in red-cell size.",
        ("mp_lab_rbc_indices",),
        status="partial",
    ),
    # ------------------------------------------------ Haemoglobin variants
    _e(
        "hb_a", "Haemoglobin A", ("hb a", "hemoglobin a", "hgb a"),
        "Haemoglobin electrophoresis",
        "Haemoglobin A is the most common type of haemoglobin in healthy adults.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin.",
        ("mp_lab_electrophoresis",),
        low_note="MedlinePlus notes that levels of haemoglobin A that are too low can be "
                 "a sign of certain types of anaemia.",
    ),
    _e(
        "hb_a2", "Haemoglobin A2", ("hb a2", "hemoglobin a2", "hgb a2"),
        "Haemoglobin electrophoresis",
        "Haemoglobin electrophoresis measures the different types of haemoglobin in the "
        "blood; the report lists a value for haemoglobin A2 as one of them.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin.",
        ("mp_lab_electrophoresis",),
        status="partial",
        limitations=(
            "The approved source describes electrophoresis and the main haemoglobin "
            "types but does not give a specific description of haemoglobin A2.",
        ),
    ),
    _e(
        "hb_f", "Haemoglobin F (fetal)", ("hb f", "hemoglobin f", "fetal hemoglobin", "hgb f"),
        "Haemoglobin electrophoresis",
        "Haemoglobin F is fetal haemoglobin: it is found in unborn babies and newborns "
        "and is usually replaced by haemoglobin A by about one to two years of age.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin.",
        ("mp_lab_electrophoresis",),
        low_note="MedlinePlus notes that levels of haemoglobin F that are too high or too "
                 "low can be a sign of certain types of anaemia.",
    ),
    _e(
        "hb_s", "Haemoglobin S", ("hb s", "hemoglobin s", "hgb s"),
        "Haemoglobin electrophoresis",
        "Haemoglobin S is an abnormal haemoglobin that is associated with sickle cell "
        "disease, in which red blood cells can become stiff and sickle-shaped.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin, or a statement that it "
        "was not detected.",
        ("mp_lab_electrophoresis",),
        kind="qualitative",
        qualitative_note="A haemoglobin variant may be reported as a percentage or as "
                         "detected / not detected; the report's own wording is the guide.",
    ),
    _e(
        "hb_c", "Haemoglobin C", ("hb c", "hemoglobin c", "hgb c"),
        "Haemoglobin electrophoresis",
        "Haemoglobin C is one of the abnormal haemoglobin types that haemoglobin "
        "electrophoresis can identify.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin, or a statement that it "
        "was not detected.",
        ("mp_lab_electrophoresis",),
        kind="qualitative",
        qualitative_note="A haemoglobin variant may be reported as a percentage or as "
                         "detected / not detected; the report's own wording is the guide.",
        status="partial",
        limitations=(
            "The approved source names abnormal haemoglobin types generally but does not "
            "describe haemoglobin C in detail.",
        ),
    ),
    _e(
        "hb_d", "Haemoglobin D", ("hb d", "hemoglobin d", "hgb d"),
        "Haemoglobin electrophoresis",
        "Haemoglobin D is one of the abnormal haemoglobin types that haemoglobin "
        "electrophoresis can identify.",
        "It is measured as part of haemoglobin electrophoresis.",
        "The result is usually a percentage of total haemoglobin, or a statement that it "
        "was not detected.",
        ("mp_lab_electrophoresis",),
        kind="qualitative",
        qualitative_note="A haemoglobin variant may be reported as a percentage or as "
                         "detected / not detected; the report's own wording is the guide.",
        status="partial",
        limitations=(
            "The approved source names abnormal haemoglobin types generally but does not "
            "describe haemoglobin D in detail.",
        ),
    ),
    # -------------------------------------------------------------- Liver
    _e(
        "alkaline_phosphatase", "Alkaline phosphatase (ALP)",
        ("alkaline phosphatase", "alp"),
        "Liver function",
        "ALP is an enzyme made mainly in the liver; it is also found in bone.",
        "It is part of a liver panel and is used alongside other tests to assess the "
        "liver and bile ducts.",
        "The result is enzyme activity in the blood, usually in units per litre (U/L).",
        ("mp_lab_lft",),
        high_note="MedlinePlus notes that high ALP can be a sign of bone disease or "
                  "liver disease, which is why it is interpreted with other results.",
    ),
    _e(
        "bilirubin_total", "Bilirubin — total",
        ("bilirubin total", "total bilirubin"),
        "Liver function",
        "Bilirubin is a waste product made when the body breaks down old red blood "
        "cells; the liver removes most of it.",
        "It is part of a liver panel and is used to assess how the liver is working.",
        "The result is the total amount of bilirubin in the blood.",
        ("mp_lab_lft",),
    ),
    _e(
        "bilirubin_direct", "Bilirubin — direct",
        ("bilirubin direct", "direct bilirubin", "conjugated bilirubin"),
        "Liver function",
        "Direct (conjugated) bilirubin is the portion of bilirubin that has been "
        "processed by the liver.",
        "It is part of a liver panel and is usually interpreted with total bilirubin.",
        "The result is the direct fraction of bilirubin in the blood.",
        ("mp_lab_lft",),
        status="partial",
    ),
    _e(
        "bilirubin_indirect", "Bilirubin — indirect",
        ("bilirubin indirect", "indirect bilirubin", "unconjugated bilirubin"),
        "Liver function",
        "Indirect (unconjugated) bilirubin is the portion of bilirubin not yet "
        "processed by the liver; it is usually calculated from the total and direct "
        "measurements.",
        "It is part of a liver panel and is interpreted with total and direct bilirubin.",
        "Because it is derived from other results, it carries their uncertainty.",
        ("mp_lab_lft",),
        status="partial",
    ),
    _e(
        "ggt", "Gamma-glutamyl transferase (GGT)",
        ("gamma glutamyl transferase ggt", "ggt", "gamma gt"),
        "Liver function",
        "GGT is an enzyme found mainly in the liver.",
        "It is part of a liver panel and is often interpreted alongside ALP.",
        "The result is enzyme activity in the blood.",
        ("mp_lab_lft",),
    ),
    _e(
        "sgot", "Aspartate aminotransferase (AST)",
        ("aspartate aminotransferase sgot", "sgot", "ast"),
        "Liver function",
        "AST is an enzyme found in the liver and in other tissues.",
        "It is part of a liver panel and can be used to look for liver damage or to "
        "monitor a known liver condition.",
        "The result is enzyme activity in the blood.",
        ("mp_lab_lft",),
    ),
    _e(
        "sgpt", "Alanine transaminase (ALT)",
        ("alanine transaminase sgpt", "sgpt", "alt"),
        "Liver function",
        "ALT is an enzyme mainly made in the liver.",
        "It is part of a liver panel and can be used to look for liver damage or to "
        "monitor a known liver condition.",
        "The result is enzyme activity in the blood.",
        ("mp_lab_lft",),
    ),
    _e(
        "sgot_sgpt_ratio", "AST/ALT ratio",
        ("sgot sgpt ratio", "ast alt ratio"),
        "Liver function",
        "This is a calculated ratio of AST to ALT, two liver enzymes.",
        "It is derived from other results and may be used by clinicians as one part of "
        "a liver assessment.",
        "Because it is calculated, it reflects the uncertainty of both enzymes.",
        ("mp_lab_lft",),
        status="partial",
    ),
    _e(
        "total_protein", "Total protein",
        ("protein total", "total protein"),
        "Liver function",
        "Total protein measures the total amount of protein in the blood, which "
        "includes albumin and globulins, proteins mainly made in the liver.",
        "It is part of a liver panel and is interpreted with albumin.",
        "The result combines several protein fractions.",
        ("mp_lab_lft", "mp_lab_cmp"),
    ),
    _e(
        "albumin", "Albumin",
        ("albumin", "albumin serum", "serum albumin"),
        "Liver function",
        "Albumin is the main protein in the blood and is made in the liver.",
        "It is part of a liver panel and is interpreted with total protein.",
        "The result is the amount of albumin in the blood.",
        ("mp_lab_lft", "mp_lab_cmp"),
    ),
    _e(
        "globulin", "Globulin",
        ("globulin", "serum globulin"),
        "Liver function",
        "Globulins are a group of blood proteins that include antibodies.",
        "The globulin value is usually derived from total protein and albumin.",
        "The result is a calculated fraction rather than a direct measurement on most "
        "reports.",
        ("mp_lab_lft",),
        status="partial",
    ),
    _e(
        "albumin_globulin_ratio", "Albumin/globulin ratio",
        ("albumin globulin ratio", "serum alb globulin ratio", "a g ratio"),
        "Liver function",
        "This is a calculated ratio of albumin to globulin.",
        "It is derived from the albumin and total-protein results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_lft",),
        status="partial",
    ),
    # ------------------------------------------------------------ Kidney
    _e(
        "blood_urea_nitrogen", "Blood urea nitrogen (BUN)",
        ("blood urea nitrogen bun", "bun"),
        "Kidney function",
        "BUN measures the nitrogen part of urea, a waste product the kidneys filter "
        "from the blood and remove in urine.",
        "It is part of a metabolic panel used to assess kidney function.",
        "The result is a concentration in the blood.",
        ("mp_lab_cmp",),
    ),
    _e(
        "creatinine", "Creatinine — serum",
        ("creatinine", "creatinine serum", "serum creatinine"),
        "Kidney function",
        "Creatinine is a waste product that the kidneys filter out of the blood and "
        "remove through urine.",
        "It is part of a metabolic panel used to assess kidney function.",
        "The result is a concentration in the blood.",
        ("mp_lab_cmp",),
    ),
    _e(
        "urea", "Urea",
        ("urea", "urea calculated"),
        "Kidney function",
        "Urea is a waste product of protein breakdown; BUN measures its nitrogen "
        "content.",
        "It is derived from BUN and reported by some laboratories.",
        "Because it is calculated from BUN, it reflects BUN's uncertainty.",
        ("mp_lab_cmp",),
        status="partial",
    ),
    _e(
        "bun_creatinine_ratio", "BUN/creatinine ratio",
        ("bun sr creatinine ratio", "bun creatinine ratio"),
        "Kidney function",
        "This is a calculated ratio of BUN to creatinine.",
        "It is derived from two other results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_cmp",),
        status="partial",
    ),
    _e(
        "egfr", "Estimated glomerular filtration rate (eGFR)",
        ("est glomerular filtration rate egfr", "egfr", "gfr"),
        "Kidney function",
        "eGFR is a calculated estimate of how well the kidneys filter, derived from a "
        "creatinine measurement.",
        "It is reported alongside creatinine to help describe kidney function.",
        "The value is an estimate from a formula, not a direct measurement.",
        ("mp_lab_cmp",),
        status="partial",
        limitations=(
            "The approved source describes creatinine as a waste product filtered by "
            "the kidneys but does not describe how eGFR is calculated or interpreted; "
            "MediRead therefore does not compare it with the printed ranges in detail.",
        ),
    ),
    # -------------------------------------------------------- Electrolytes
    _e(
        "sodium", "Sodium",
        ("sodium",),
        "Electrolytes",
        "Sodium is an electrolyte — an electrically charged mineral that helps control "
        "the amount of fluid in the body and the balance of acids and bases.",
        "It is part of a metabolic or electrolyte panel.",
        "The result is a concentration in the blood, usually in mmol/L.",
        ("mp_lab_cmp",),
    ),
    _e(
        "potassium", "Potassium",
        ("potassium",),
        "Electrolytes",
        "Potassium is an electrolyte that helps control fluid balance and the balance "
        "of acids and bases in the body.",
        "It is part of a metabolic or electrolyte panel.",
        "The result is a concentration in the blood, usually in mmol/L.",
        ("mp_lab_cmp",),
    ),
    _e(
        "chloride", "Chloride",
        ("chloride",),
        "Electrolytes",
        "Chloride is an electrolyte that helps control fluid balance and the balance "
        "of acids and bases in the body.",
        "It is part of a metabolic or electrolyte panel.",
        "The result is a concentration in the blood, usually in mmol/L.",
        ("mp_lab_cmp",),
    ),
    _e(
        "calcium", "Calcium",
        ("calcium",),
        "Electrolytes",
        "Calcium is one of the most important minerals in the body; most of it is "
        "stored in bones and teeth, and the amount in blood is needed for nerves, "
        "muscles and the heart to work properly.",
        "It is part of a metabolic panel.",
        "The result is the amount of calcium in the blood.",
        ("mp_lab_cmp",),
    ),
    # -------------------------------------------------------------- Lipid
    _e(
        "total_cholesterol", "Total cholesterol",
        ("total cholesterol",),
        "Lipid profile",
        "Total cholesterol measures the total amount of cholesterol in the blood, "
        "including HDL and LDL cholesterol.",
        "It is the headline number of a lipid panel, which is used to assess "
        "heart-disease risk.",
        "The result is a concentration, usually in mg/dL or mmol/L.",
        ("mp_lab_lipid",),
        high_note="MedlinePlus explains that too much cholesterol in the blood can "
                  "contribute to plaque building up in arteries over time, and that "
                  "healthy levels depend on age and other risk factors.",
    ),
    _e(
        "ldl_cholesterol", "LDL cholesterol",
        ("ldl cholesterol", "ldl cholesterol direct", "ldl"),
        "Lipid profile",
        "LDL (low-density lipoprotein) cholesterol is the main source of cholesterol "
        "build-up in the arteries.",
        "It is part of a lipid panel and is a key input to heart-disease risk assessment.",
        "The result may be measured directly or estimated from other lipid results.",
        ("mp_lab_lipid",),
        high_note="MedlinePlus explains that too much LDL cholesterol in the blood "
                  "increases the risk of coronary artery disease and other heart "
                  "diseases, and that a healthy level for you depends on your age, "
                  "family history and other risk factors.",
        limitations=(
            "If the report labels LDL as calculated, it is an estimate derived from "
            "other lipid results (MedlinePlus).",
        ),
    ),
    _e(
        "hdl_cholesterol", "HDL cholesterol",
        ("hdl cholesterol", "hdl cholesterol direct", "hdl"),
        "Lipid profile",
        "HDL (high-density lipoprotein) cholesterol helps remove LDL cholesterol from "
        "the blood.",
        "It is part of a lipid panel and is used in heart-disease risk assessment.",
        "The result is a concentration, usually in mg/dL or mmol/L.",
        ("mp_lab_lipid",),
        low_note="MedlinePlus notes that a higher HDL level may help reduce the risk of "
                 "heart attack or stroke, and that healthy levels depend on age and "
                 "other risk factors.",
    ),
    _e(
        "triglycerides", "Triglycerides",
        ("triglycerides", "triglyceride"),
        "Lipid profile",
        "Triglycerides are a type of fat found in the blood.",
        "They are measured as part of a lipid panel.",
        "The result is a concentration, usually in mg/dL or mmol/L.",
        ("mp_lab_lipid",),
        high_note="MedlinePlus notes that high triglyceride levels may increase the risk "
                  "of heart disease, especially in women.",
    ),
    _e(
        "vldl_cholesterol", "VLDL cholesterol",
        ("vldl cholesterol", "vldl"),
        "Lipid profile",
        "VLDL (very low-density lipoprotein) mainly carries triglycerides in the blood.",
        "It is not usually part of a routine lipid panel; it is often estimated from "
        "the triglyceride result.",
        "The result may be calculated rather than measured directly.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    _e(
        "non_hdl_cholesterol", "Non-HDL cholesterol",
        ("non hdl cholesterol",),
        "Lipid profile",
        "Non-HDL cholesterol is the portion of total cholesterol that is not HDL.",
        "It is used alongside other lipid results in heart-disease risk assessment.",
        "It is usually calculated from total cholesterol and HDL cholesterol.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    _e(
        "ldl_hdl_ratio", "LDL/HDL ratio",
        ("ldl hdl ratio",),
        "Lipid profile",
        "This is a calculated ratio of LDL cholesterol to HDL cholesterol.",
        "It is derived from two lipid results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    _e(
        "hdl_ldl_ratio", "HDL/LDL ratio",
        ("hdl ldl ratio",),
        "Lipid profile",
        "This is a calculated ratio of HDL cholesterol to LDL cholesterol.",
        "It is derived from two lipid results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    _e(
        "tc_hdl_ratio", "Total cholesterol/HDL ratio",
        ("tc hdl cholesterol ratio", "total cholesterol hdl ratio"),
        "Lipid profile",
        "This is a calculated ratio of total cholesterol to HDL cholesterol.",
        "It is derived from two lipid results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    _e(
        "trig_hdl_ratio", "Triglyceride/HDL ratio",
        ("trig hdl ratio", "triglyceride hdl ratio"),
        "Lipid profile",
        "This is a calculated ratio of triglycerides to HDL cholesterol.",
        "It is derived from two lipid results.",
        "Because it is calculated, it reflects the uncertainty of both inputs.",
        ("mp_lab_lipid",),
        status="partial",
    ),
    # ------------------------------------------------------------ Thyroid
    _e(
        "tsh", "TSH (thyroid-stimulating hormone)",
        ("tsh", "tsh ultrasensitive", "thyroid stimulating hormone",
         "thyroid stimulating hormone tsh", "thyrotropin"),
        "Thyroid profile",
        "TSH is a hormone made by the pituitary gland that tells the thyroid how much "
        "thyroid hormone to make.",
        "It is used to find out how well the thyroid is working.",
        "The result is a concentration of TSH in the blood.",
        ("mp_lab_tsh",),
        low_note="MedlinePlus explains that a TSH level that is too low may be a sign of "
                 "a thyroid problem, but that TSH can be high or low even when the "
                 "thyroid is healthy — for example during illness, in older age, or in "
                 "pregnancy.",
        high_note="MedlinePlus explains that a TSH level that is too high may be a sign "
                  "of a thyroid problem, but that TSH can be high or low even when the "
                  "thyroid is healthy — for example during illness, in older age, or in "
                  "pregnancy.",
        limitations=(
            "A TSH result cannot show what is causing a thyroid problem; MedlinePlus "
            "notes that other thyroid tests are usually needed.",
        ),
    ),
    _e(
        "t4", "Thyroxine (T4)",
        ("total thyroxine t4", "t4", "thyroxine"),
        "Thyroid profile",
        "T4 is one of the thyroid hormones; thyroid hormones affect how the body uses "
        "energy and influence many organs.",
        "It is measured with TSH to investigate thyroid function.",
        "The result is a concentration of thyroxine in the blood.",
        ("mp_lab_tsh",),
        status="partial",
        limitations=(
            "The approved source describes thyroid hormone testing but does not give "
            "detailed T4 reference information; MediRead keeps its description general.",
        ),
    ),
    _e(
        "t3", "Triiodothyronine (T3)",
        ("total triiodothyronine t3", "t3", "triiodothyronine"),
        "Thyroid profile",
        "T3 is one of the thyroid hormones; thyroid hormones affect how the body uses "
        "energy and influence many organs.",
        "It is measured with TSH and T4 to investigate thyroid function.",
        "The result is a concentration of triiodothyronine in the blood.",
        ("mp_lab_tsh",),
        status="partial",
        limitations=(
            "The approved source describes thyroid hormone testing but does not give "
            "detailed T3 reference information; MediRead keeps its description general.",
        ),
    ),
    # ----------------------------------------------------------- Diabetes
    _e(
        "hba1c", "Haemoglobin A1c",
        ("hba1c", "hba1c hplc", "glycated hemoglobin", "glycohemoglobin", "a1c"),
        "Glucose and HbA1c",
        "HbA1c measures the percentage of red blood cells that have glucose attached "
        "to their haemoglobin, which reflects average blood glucose over the past two "
        "to three months.",
        "It is used to screen for or monitor diabetes and prediabetes.",
        "The result is a percentage.",
        ("mp_lab_hba1c",),
        low_note="MedlinePlus describes results below about 5.7% in the general "
                 "reference categories it lists, and notes that what is normal for you "
                 "depends on your health, age and other factors.",
        high_note="MedlinePlus describes results of 6.5% or higher in the reference "
                  "categories it lists for diabetes, and notes that providers usually "
                  "use more than one test before diagnosing diabetes.",
        limitations=(
            "MedlinePlus notes that conditions affecting red blood cells, kidney "
            "failure and liver disease can make HbA1c less reliable.",
            "The ranges MedlinePlus lists are described there as a guide, not a "
            "diagnosis; your report may use different categories.",
        ),
    ),
    _e(
        "average_blood_glucose", "Average blood glucose (estimated)",
        ("average blood glucose abg", "estimated average glucose", "eag"),
        "Glucose and HbA1c",
        "This is an estimate of average blood glucose derived from an HbA1c result.",
        "It is reported by some laboratories alongside HbA1c.",
        "The value is calculated from HbA1c, not measured directly.",
        ("mp_lab_hba1c",),
        status="partial",
        limitations=(
            "The approved source explains that HbA1c reflects average glucose but does "
            "not describe how the estimated average glucose is calculated.",
        ),
    ),
    _e(
        "fasting_glucose", "Fasting blood glucose",
        ("fasting blood sugar glucose", "fasting blood sugar", "fasting glucose",
         "glucose fasting"),
        "Glucose and HbA1c",
        "Glucose is the body's main source of energy; a fasting glucose test measures "
        "the amount of glucose in the blood after not eating for a period.",
        "It is used to screen for or monitor diabetes.",
        "The result is a concentration, usually in mg/dL or mmol/L.",
        ("mp_lab_cmp", "mp_lab_hba1c"),
        status="partial",
    ),
    # -------------------------------------------------------- Coagulation
    _e(
        "prothrombin_time", "Prothrombin time (PT)",
        ("prothrombin time", "pt"),
        "Coagulation (PT/INR)",
        "Prothrombin time measures how many seconds it takes for a clot to form in a "
        "blood sample.",
        "It is used to check clotting, to monitor anticoagulant treatment and to help "
        "assess liver function.",
        "The result is reported in seconds.",
        ("mp_lab_ptinr",),
    ),
    _e(
        "inr", "International normalised ratio (INR)",
        ("international normalized ratio", "inr"),
        "Coagulation (PT/INR)",
        "INR is a ratio calculated from the prothrombin time that makes results easier "
        "to compare between laboratories and test methods.",
        "It is most often used to monitor anticoagulant treatment such as warfarin and "
        "to investigate unusual bleeding or clotting.",
        "The result is a ratio without units.",
        ("mp_lab_ptinr",),
        low_note="MedlinePlus explains that an INR that is too low may mean blood clots "
                 "too easily, and that a provider may change treatment based on the "
                 "result.",
        high_note="MedlinePlus explains that an INR that is too high may mean blood is "
                  "taking longer than normal to clot, and that a provider may change "
                  "treatment based on the result.",
        limitations=(
            "INR interpretation depends on whether you take an anticoagulant and on "
            "the target range your provider set; the printed interval is not the same "
            "as a treatment target.",
        ),
    ),
    # --------------------------------------------------------------- Urine
    _e(
        "urine_colour", "Urine colour", ("colour", "color", "urine color", "urine colour"),
        "Urine analysis", "A urinalysis checks the colour of your urine.",
        "It is part of a routine urinalysis.",
        "The result is a description rather than a number.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Colour is descriptive and is interpreted together with "
                         "appearance, concentration and other urine tests.",
    ),
    _e(
        "urine_appearance", "Urine appearance",
        ("appearance", "urine appearance", "clarity"),
        "Urine analysis",
        "A urinalysis checks whether urine is clear or cloudy.",
        "It is part of a routine urinalysis.",
        "The result is a description rather than a number.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Appearance is descriptive and is interpreted together with "
                         "colour and other urine tests.",
    ),
    _e(
        "urine_ph", "Urine pH", ("ph", "urine ph", "ph urine"),
        "Urine analysis",
        "A urinalysis checks the pH level, which describes how acidic or alkaline the "
        "urine is.",
        "It is part of a routine urinalysis.",
        "The result is a pH value.",
        ("mp_topic_urinalysis",),
    ),
    _e(
        "urine_protein", "Protein in urine",
        ("urinary protein", "protein urine", "urine protein"),
        "Urine analysis",
        "A urinalysis checks for protein in urine, which is not normally present in "
        "significant amounts.",
        "It is part of a routine urinalysis and can be used when kidney problems are "
        "being assessed.",
        "The result is usually a qualitative description or a concentration.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Protein is usually reported as absent, trace or a grade; the "
                         "report's reference column is the best guide to its wording.",
    ),
    _e(
        "urine_glucose", "Glucose in urine",
        ("urinary glucose", "glucose urine", "urine glucose"),
        "Urine analysis",
        "A urinalysis checks for glucose in urine.",
        "It is part of a routine urinalysis and may be used when diabetes is being "
        "assessed.",
        "The result is usually a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Glucose is usually reported as absent or as a grade; the "
                         "report's reference column is the best guide to its wording.",
    ),
    _e(
        "urine_ketone", "Ketones in urine",
        ("urine ketone", "ketones urine", "ketone"),
        "Urine analysis",
        "A urinalysis checks for ketones in urine.",
        "It is part of a routine urinalysis.",
        "The result is usually a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Ketones are usually reported as absent, trace or a grade.",
    ),
    _e(
        "urine_bilirubin", "Bilirubin in urine",
        ("urinary bilirubin", "bilirubin urine", "urine bilirubin"),
        "Urine analysis",
        "A urinalysis checks for bilirubin in urine.",
        "It is part of a routine urinalysis and may be used when liver or bile-duct "
        "problems are being assessed.",
        "The result is usually a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Bilirubin is usually reported as absent or present.",
    ),
    _e(
        "urine_blood", "Blood in urine",
        ("urine blood", "blood urine", "haematuria"),
        "Urine analysis",
        "A urinalysis checks for blood in urine.",
        "It is part of a routine urinalysis.",
        "The result is usually a qualitative description or a count of red cells.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Blood is usually reported as absent, trace or a grade, and "
                         "may be checked again with microscopy.",
    ),
    _e(
        "nitrite", "Nitrite in urine", ("nitrite", "nitrites"),
        "Urine analysis",
        "A urinalysis checks whether urine contains bacteria or other germs; nitrite "
        "is one of the markers reported on urine test strips.",
        "It is part of a routine urinalysis.",
        "The result is usually reported as negative or positive.",
        ("mp_topic_urinalysis",), kind="qualitative", status="partial",
        qualitative_note="Nitrite is reported as negative or positive; a positive result is usually interpreted together with other urine findings.",
    ),
    _e(
        "uret_leucocytes", "Leucocytes in urine",
        ("urinary leucocytes", "urinary leucocytes pus cells", "leucocytes"),
        "Urine analysis",
        "A urinalysis can check for cells in urine, including white blood cells.",
        "It is part of a routine urinalysis.",
        "The result is usually a count per high-power field or a qualitative grade.",
        ("mp_topic_urinalysis",), kind="qualitative", status="partial",
        qualitative_note="Leucocytes are reported as a count per high-power field or as a qualitative grade.",
    ),
    _e(
        "urine_rbc", "Red blood cells in urine (microscopy)",
        ("red blood cells",),
        "Urine analysis",
        "A urinalysis can check for cells in urine, including red blood cells.",
        "It is part of the microscopic examination of a urinalysis.",
        "The result is usually a count per high-power field.",
        ("mp_topic_urinalysis",), kind="qualitative", status="partial",
        qualitative_note="Red cells are reported as a count per high-power field and are usually interpreted with the urine blood result.",
    ),
    _e(
        "casts", "Casts in urine", ("casts", "urinary casts"),
        "Urine analysis",
        "A urinalysis checks for casts, which are tube-shaped structures formed in the "
        "kidney tubules.",
        "They are part of the microscopic examination of a urinalysis.",
        "The result is a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Casts are reported by type or as absent.",
    ),
    _e(
        "crystals", "Crystals in urine", ("crystals", "urinary crystals"),
        "Urine analysis",
        "A urinalysis checks for crystals in urine.",
        "They are part of the microscopic examination of a urinalysis.",
        "The result is a qualitative description of the crystal type, if any.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Crystals are reported by type or as absent.",
    ),
    _e(
        "bacteria_urine", "Bacteria in urine", ("bacteria", "bacteria urine"),
        "Urine analysis",
        "A urinalysis checks whether urine contains bacteria or other germs.",
        "It is part of a routine urinalysis.",
        "The result is usually a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative",
        qualitative_note="Bacteria are usually reported as absent, present or a grade.",
    ),
    _e(
        "mucus_urine", "Mucus in urine", ("mucus",),
        "Urine analysis",
        "A urinalysis can note the presence of mucus in urine.",
        "It is part of the microscopic examination of a urinalysis.",
        "The result is a qualitative description.",
        ("mp_topic_urinalysis",), kind="qualitative", status="partial",
        qualitative_note="Mucus is reported as absent, present or a grade.",
    ),
)

ENTRIES_BY_ID: dict[str, KnowledgeEntry] = {entry.test_id: entry for entry in ENTRIES}
