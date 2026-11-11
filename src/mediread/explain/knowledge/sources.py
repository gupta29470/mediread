"""Approved medical sources with provenance and licence status.

Licensing determination (checked 2026-11-07)
--------------------------------------------
MedlinePlus publishes its reuse rules at
https://medlineplus.gov/about/using/usingcontent/ . That page states that
**medical test information** and **health-topic summaries** are works of the
federal government in the public domain and may be reproduced and redistributed,
provided MedlinePlus is acknowledged. It separately states that **A.D.A.M.
Medical Encyclopedia** content is copyrighted and licensed only for use on
MedlinePlus, and that copyrighted content may not be ingested or reused.

Consequences for this catalogue:

* Only ``medlineplus.gov/lab-tests/...`` and ``medlineplus.gov/<topic>.html``
  pages are used as knowledge sources.
* ``medlineplus.gov/ency/article/...`` (A.D.A.M.) pages are **excluded**, even
  where they would be convenient. One was fetched during the review and
  discarded; see :data:`EXCLUDED_SOURCES`.
* Every entry summarises the source in original wording. No passage is copied
  verbatim, and no more than a short factual summary is derived.
* Attribution is rendered in the explanation output and stored here.

Nothing in this file is medical advice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeSource:
    source_id: str
    title: str
    organization: str
    url: str
    accessed: str
    licence: str
    licence_note: str
    used_for: tuple[str, ...]


_ACCESSED = "2026-11-07"
_NLM_LICENCE = "public-domain (US federal government work)"
_NLM_NOTE = (
    "MedlinePlus medical-test and health-topic content is public domain; "
    "acknowledge 'Source: MedlinePlus, National Library of Medicine'. "
    "A.D.A.M. encyclopedia content is excluded."
)


SOURCES: dict[str, KnowledgeSource] = {
    "mp_lab_understanding": KnowledgeSource(
        source_id="mp_lab_understanding",
        title="How to Understand Your Lab Results",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/how-to-understand-your-lab-results/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "reference ranges are laboratory-specific and vary",
            "results outside a range may or may not indicate a health problem",
            "results inside a range do not guarantee health",
            "factors that can affect results",
            "units of measurement differ between tests",
        ),
    ),
    "mp_lab_cbc": KnowledgeSource(
        source_id="mp_lab_cbc",
        title="Complete Blood Count (CBC)",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/complete-blood-count-cbc/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "what a CBC measures (red cells, white cells, platelets, haemoglobin, haematocrit, MCV)",
            "common reasons a CBC is ordered",
            "abnormal counts may have non-disease explanations",
        ),
    ),
    "mp_lab_rbc_indices": KnowledgeSource(
        source_id="mp_lab_rbc_indices",
        title="Red Blood Cell (RBC) Indices",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/red-blood-cell-rbc-indices/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "definitions of MCV, MCH, MCHC and RDW",
            "indices describe red-cell size and haemoglobin content",
            "indices are interpreted together, not in isolation",
        ),
    ),
    "mp_lab_differential": KnowledgeSource(
        source_id="mp_lab_differential",
        title="Blood Differential",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/blood-differential/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "the five white-cell types and their roles",
            "high and low white-cell counts have many possible causes",
            "abnormal results do not always mean treatment is needed",
        ),
    ),
    "mp_lab_lft": KnowledgeSource(
        source_id="mp_lab_lft",
        title="Liver Function Tests",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/liver-function-tests/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "what liver function tests measure",
            "liver tests alone usually cannot diagnose a specific disease",
            "abnormal results can have non-liver causes",
        ),
    ),
    "mp_lab_cmp": KnowledgeSource(
        source_id="mp_lab_cmp",
        title="Comprehensive Metabolic Panel (CMP)",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/comprehensive-metabolic-panel-cmp/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "what the panel measures: glucose, calcium, electrolytes, albumin, protein, liver enzymes, bilirubin, BUN, creatinine",
            "electrolytes help control fluid and acid-base balance",
            "BUN and creatinine are waste products filtered by the kidneys",
        ),
    ),
    "mp_lab_lipid": KnowledgeSource(
        source_id="mp_lab_lipid",
        title="Cholesterol Levels",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/cholesterol-levels/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "what a lipid panel measures (total, LDL, HDL, triglycerides, VLDL)",
            "cholesterol is used to assess heart-disease risk",
            "healthy levels depend on age and other risk factors",
            "LDL may be calculated or measured directly",
        ),
    ),
    "mp_lab_hba1c": KnowledgeSource(
        source_id="mp_lab_hba1c",
        title="Hemoglobin A1C (HbA1c) Test",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/hemoglobin-a1c-hba1c-test/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "HbA1c reflects average blood glucose over about two to three months",
            "common reference categories are described as a guide, not a diagnosis",
            "conditions affecting red blood cells can make HbA1c less reliable",
        ),
    ),
    "mp_lab_tsh": KnowledgeSource(
        source_id="mp_lab_tsh",
        title="TSH (Thyroid-stimulating hormone) Test",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/tsh-thyroid-stimulating-hormone-test/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "TSH controls how much thyroid hormone the thyroid makes",
            "TSH can be high or low even when the thyroid is healthy",
            "other thyroid tests are used to find the cause",
        ),
    ),
    "mp_lab_ptinr": KnowledgeSource(
        source_id="mp_lab_ptinr",
        title="Prothrombin Time Test and INR (PT/INR)",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/prothrombin-time-test-and-inr-ptinr/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "PT measures how long blood takes to clot",
            "INR standardises PT results across laboratories",
            "PT/INR is used to monitor anticoagulant treatment and check clotting",
        ),
    ),
    "mp_lab_electrophoresis": KnowledgeSource(
        source_id="mp_lab_electrophoresis",
        title="Hemoglobin Electrophoresis",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/lab-tests/hemoglobin-electrophoresis/",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "electrophoresis measures the different types of haemoglobin in the blood",
            "Hb A is the most common haemoglobin in healthy adults; Hb F is fetal haemoglobin",
            "Hb S is associated with sickle cell disease; other abnormal types exist",
            "abnormal haemoglobin can change red-cell shape and cause anaemia",
        ),
    ),
    "mp_topic_urinalysis": KnowledgeSource(
        source_id="mp_topic_urinalysis",
        title="Urinalysis",
        organization="MedlinePlus, U.S. National Library of Medicine",
        url="https://medlineplus.gov/urinalysis.html",
        accessed=_ACCESSED,
        licence=_NLM_LICENCE,
        licence_note=_NLM_NOTE,
        used_for=(
            "urinalysis checks colour, appearance, pH, and substances such as protein, glucose, ketones and bilirubin",
            "it can check for cells, crystals, casts, bacteria and other germs",
            "it is used for urinary-tract, kidney and diabetes assessment and general checkups",
        ),
    ),
}

# Sources deliberately not used. Recorded so the decision is auditable.
EXCLUDED_SOURCES: dict[str, dict[str, str]] = {
    "medlineplus_adam_encyclopedia": {
        "reason": (
            "A.D.A.M. Medical Encyclopedia content is copyrighted and licensed "
            "for display on MedlinePlus only. The MedlinePlus reuse page states "
            "that this material may not be ingested or reused, and the page's own "
            "notice prohibits derivative works and AI ingestion. Excluded from the "
            "knowledge base; only a plain link could be shown, and no content is "
            "derived from it."
        ),
        "checked": "https://medlineplus.gov/about/using/usingcontent/",
    },
    "medlineplus_encyclopedia_thyroid": {
        "reason": (
            "Fetched while evaluating coverage of thyroid tests, then discarded: "
            "the article is A.D.A.M. content with an explicit copyright notice. "
            "Replaced by the NLM-authored TSH lab-test page."
        ),
        "checked": "https://medlineplus.gov/ency/article/003444.htm",
    },
}

ATTRIBUTION = "Source: MedlinePlus, National Library of Medicine (public domain)."

KNOWLEDGE_VERSION = "mediread.knowledge/1"


def get_source(source_id: str) -> KnowledgeSource | None:
    return SOURCES.get(source_id)
