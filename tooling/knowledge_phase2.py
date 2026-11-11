"""Phase 2: add researched entries with claim-level evidence from MedlinePlus.

Each entry below summarises a public-domain MedlinePlus medical-test page in
original wording. The `evidence` row stores a short verbatim excerpt from the
cited page plus its URL, so a reviewer can check the claim without guessing. The
page HTML is cached under `.cache/knowledge_pages/` by the fetch step; this script
fails rather than inventing an excerpt when the cache is missing.

Run:  .venv/bin/python tooling/knowledge_phase2.py
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from mediread.knowledge.models import Evidence, KnowledgeTest, Source
from mediread.knowledge.package import load_package, save_package

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "knowledge" / "mediread-knowledge.json"
CACHE = REPO / ".cache" / "knowledge_pages"
ACCESSED = "2026-11-07"

LIMITS = [
    "The reference interval printed on your report is specific to the laboratory that produced it; intervals from other laboratories are not interchangeable.",
    "A result outside the printed interval may or may not reflect a health problem, and a result inside the interval does not by itself guarantee health.",
    "This explanation is general education, not a diagnosis; discuss the result with the clinician who ordered it.",
]

ENTRIES = [
    {
        "test_id": "vitamin_d",
        "canonical_name": "Vitamin D (25-hydroxy)",
        "category": "Vitamins",
        "synonyms": ["25-OH vitamin D", "25 hydroxy vitamin D", "Vitamin D 25 OH", "Calcidiol"],
        "slug": "vitamin-d-test",
        "what_it_measures": (
            "A vitamin D test measures how much vitamin D is circulating in the blood. "
            "Vitamin D helps the body absorb calcium and supports bones, muscles, nerves "
            "and the immune system. Results are often reported as total vitamin D, or "
            "separately as vitamin D2 and vitamin D3."
        ),
        "why_it_is_ordered": (
            "It is usually ordered when a clinician suspects too little or too much "
            "vitamin D — for example with bone pain, muscle weakness, low bone density "
            "or a condition that affects vitamin D absorption."
        ),
        "high": (
            "A high vitamin D result is interpreted together with supplements and "
            "medical history; very high levels usually reflect intake rather than a "
            "disease found by the test alone."
        ),
        "low": (
            "A low result may reflect limited sun exposure, low intake or poor "
            "absorption, but the printed interval and the clinical context decide how "
            "it is interpreted."
        ),
    },
    {
        "test_id": "uric_acid",
        "canonical_name": "Uric acid",
        "category": "Kidney function",
        "synonyms": ["Serum uric acid", "Urate", "Uric acid serum"],
        "slug": "uric-acid-test",
        "what_it_measures": (
            "A uric acid test measures the amount of uric acid in blood or urine. Uric "
            "acid is a normal waste product made when the body breaks down purines, "
            "which come from cells and from some foods."
        ),
        "why_it_is_ordered": (
            "It is often ordered when someone has symptoms of gout, kidney stones, or "
            "another condition associated with unusual uric acid levels."
        ),
        "high": (
            "A high blood uric acid result can occur when the body makes too much uric "
            "acid or when the kidneys remove too little; diet also affects it."
        ),
        "low": None,
    },
    {
        "test_id": "iron_panel",
        "canonical_name": "Iron tests",
        "category": "Iron studies",
        "synonyms": ["Serum iron", "Iron studies", "Iron and TIBC", "Serum iron level"],
        "slug": "iron-tests",
        "what_it_measures": (
            "Iron tests measure substances in the blood that describe iron status, "
            "such as serum iron, the iron-binding capacity of transferrin and the "
            "percentage of transferrin that is saturated."
        ),
        "why_it_is_ordered": (
            "They are ordered when iron deficiency or iron overload is suspected, or "
            "when anaemia needs to be characterised."
        ),
        "high": (
            "A high iron result can reflect increased iron stores or recent iron "
            "intake; it is interpreted with the other iron tests, not alone."
        ),
        "low": (
            "A low iron result may reflect low stores or an ongoing demand for iron; "
            "the pattern across the iron tests matters more than one value."
        ),
    },
    {
        "test_id": "microalbumin",
        "canonical_name": "Microalbumin creatinine ratio",
        "category": "Urine analysis",
        "synonyms": ["Microalbumin", "Urine albumin", "Albumin creatinine ratio", "ACR", "UACR"],
        "slug": "microalbumin-creatinine-ratio",
        "what_it_measures": (
            "A microalbumin creatinine ratio test compares the amount of albumin in a "
            "urine sample with the amount of creatinine, which adjusts for how "
            "concentrated the urine is. Albumin is a protein that should mostly stay in "
            "the blood."
        ),
        "why_it_is_ordered": (
            "It is usually ordered when someone is at higher risk of kidney disease — "
            "for example with diabetes or high blood pressure — because early kidney "
            "disease often has no symptoms."
        ),
        "high": (
            "A higher ratio may suggest albumin is passing into the urine, but "
            "temporary increases can follow exercise, fever or other illness, so a "
            "repeated test is common."
        ),
        "low": None,
    },
    {
        "test_id": "rheumatoid_factor",
        "canonical_name": "Rheumatoid factor",
        "category": "Inflammation markers",
        "synonyms": ["RF", "Rheumatoid factor (RF)", "RA factor"],
        "slug": "rheumatoid-factor-rf-test",
        "what_it_measures": (
            "A rheumatoid factor test measures rheumatoid factor in the blood, an "
            "antibody that attacks healthy tissue rather than germs. It is one piece "
            "of information used when assessing joint symptoms, not a diagnosis by "
            "itself."
        ),
        "why_it_is_ordered": (
            "It may be ordered when someone has joint pain, stiffness, tenderness or "
            "swelling that could suggest rheumatoid arthritis."
        ),
        "high": (
            "A positive result does not by itself diagnose rheumatoid arthritis: "
            "rheumatoid factor can be found in other conditions and in some healthy "
            "older people."
        ),
        "low": None,
    },
    {
        "test_id": "crp",
        "canonical_name": "C-reactive protein",
        "category": "Inflammation markers",
        "synonyms": ["CRP", "C-reactive protein", "hs-CRP", "High sensitivity CRP"],
        "slug": "c-reactive-protein-crp-test",
        "what_it_measures": (
            "A C-reactive protein test measures CRP in the blood. The liver makes CRP "
            "in response to inflammation, which is the body's response to injury, "
            "infection or other disease."
        ),
        "why_it_is_ordered": (
            "It may be ordered with symptoms of a bacterial infection, to monitor a "
            "chronic inflammatory condition, or to check for infection after surgery."
        ),
        "high": (
            "A raised CRP can reflect inflammation, but it does not say where the "
            "inflammation is or what caused it; the printed interval and the context "
            "guide interpretation."
        ),
        "low": None,
    },
]

_SECTION_RE = {
    "what": re.compile(r"What (?:is|are) [^?]*\?\s*(.{80,900}?)(?:\.\s)", re.S),
    "why": re.compile(r"Why do I need [^?]*\?\s*(.{80,900}?)(?:\.\s)", re.S),
}


def page_text(slug: str) -> tuple[str, str]:
    path = CACHE / f"{slug}.html"
    if not path.exists():
        raise SystemExit(f"missing cached page {path}; fetch it first")
    raw = path.read_text(encoding="utf-8", errors="ignore")
    title = re.search(r"<title>(.*?)</title>", raw, re.S)
    text = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text))
    return (html.unescape(title.group(1)).strip() if title else slug), text


def excerpt(slug: str, section: str) -> str:
    _title, text = page_text(slug)
    match = _SECTION_RE[section].search(text)
    if not match:
        raise SystemExit(f"{slug}: no {section} section found; refusing to invent an excerpt")
    return re.sub(r"\s+", " ", match.group(1)).strip()[:600]


def main() -> None:
    package, _report = load_package(PACKAGE)
    existing = package.tests_by_id
    sources = package.sources_by_id
    added_tests = 0
    added_evidence = 0

    for spec in ENTRIES:
        slug = spec["slug"]
        title, _text = page_text(slug)
        url = f"https://medlineplus.gov/lab-tests/{slug}/"
        source_id = f"mp_lab_{slug.replace('-', '_')}"
        if source_id not in sources:
            package.sources.append(
                Source(
                    source_id=source_id,
                    title=title.split(":")[0],
                    publisher="MedlinePlus, U.S. National Library of Medicine",
                    source_url=url,
                    access_date=ACCESSED,
                    content_license="public-domain (US federal government work)",
                    source_type="government",
                    publication_date=None,
                    attribution_requirements=(
                        "Acknowledge 'Source: MedlinePlus, National Library of Medicine'. "
                        "A.D.A.M. encyclopedia content is excluded."
                    ),
                    source_notes="Fetched for Phase 2 evidence; excerpt stored per claim.",
                )
            )
            sources[source_id] = package.sources[-1]

        if spec["test_id"] not in existing:
            package.tests.append(
                KnowledgeTest(
                    test_id=spec["test_id"],
                    canonical_name=spec["canonical_name"],
                    category=spec["category"],
                    what_it_measures=spec["what_it_measures"],
                    why_it_is_ordered=spec["why_it_is_ordered"],
                    general_interpretation_high=spec["high"],
                    general_interpretation_low=spec["low"],
                    limitations=tuple(LIMITS),
                    related_test_ids=(),
                    synonyms=tuple(spec["synonyms"]),
                    review_status="draft",
                    content_version=1,
                )
            )
            added_tests += 1

        claims = [
            ("what_it_measures", "what"),
            ("why_it_is_ordered", "why"),
        ]
        if spec["high"]:
            claims.append(("general_interpretation_high", "what"))
        if spec["low"]:
            claims.append(("general_interpretation_low", "what"))
        claims.append(("limitations", "what"))
        for claim_field, section in claims:
            evidence_id = f"{spec['test_id']}__{claim_field}__{source_id}"
            if any(item.evidence_id == evidence_id for item in package.evidence):
                continue
            text = excerpt(slug, section)
            package.evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    test_id=spec["test_id"],
                    source_id=source_id,
                    claim_field=claim_field,
                    supporting_excerpt_or_reference=(
                        f"{title} — {url} (accessed {ACCESSED}). Quoted excerpt: "
                        f"\u201c{text}\u201d"
                    ),
                    review_status="draft",
                )
            )
            added_evidence += 1

    save_package(package, PACKAGE)
    print(f"added {added_tests} tests, {added_evidence} evidence rows; "
          f"tests={len(package.tests)} sources={len(package.sources)} "
          f"status={package.status_counts()}")


if __name__ == "__main__":
    main()
