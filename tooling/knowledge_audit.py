"""Claim-level evidence audit for knowledge entries.

For every entry that has a quoted excerpt, check that the words carrying each claim
appear in the quoted source text. This is an *engineering* check that the claim is
traceable to the quote — it is not a clinical review, and the report says so.

Usage:
    python tooling/knowledge_audit.py            # report only
    python tooling/knowledge_audit.py --apply    # mark fully-supported entries reviewed
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from mediread.knowledge import cli
from mediread.knowledge.package import load_package

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "knowledge" / "mediread-knowledge.json"
AUDIT_LOG = REPO / "knowledge" / "audit_log.jsonl"
REPORT = REPO / "reports" / "knowledge-audit.md"

_WORD = re.compile(r"[a-z0-9]{4,}")
_STOP = {
    "this", "that", "with", "from", "your", "have", "when", "they", "their", "which",
    "will", "would", "into", "over", "than", "then", "also", "such", "more", "most",
    "some", "because", "about", "these", "those", "often", "usually", "values", "result",
    "results", "measure", "measures", "measured", "test", "tests", "level", "levels",
    "blood", "sample", "using", "used", "used", "does", "doesn", "other", "only",
}


def keywords(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOP}


def page_text(slug: str) -> str:
    """Full cached page text (paraphrases need more than the stored excerpt)."""
    path = REPO / ".cache" / "knowledge_pages" / f"{slug}.html"
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"<script.*?</script>|<style.*?</style>", "", raw, flags=re.S)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return html.unescape(re.sub(r"\s+", " ", raw))


def support(claim: str, evidence_text: str) -> float:
    claim_words = keywords(claim)
    if not claim_words:
        return 1.0
    evidence_words = keywords(evidence_text)
    return len(claim_words & evidence_words) / len(claim_words)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="mark supported entries reviewed")
    args = parser.parse_args()

    package, _report = load_package(PACKAGE)
    rows = []
    for test in package.tests:
        evidence = [
            item for item in package.evidence_for(test.test_id)
            if "Quoted excerpt" in item.supporting_excerpt_or_reference
        ]
        if not evidence:
            rows.append((test.test_id, test.canonical_name, "no-quote", {}, test.review_status))
            continue
        by_claim: dict[str, str] = {}
        for item in evidence:
            quote = item.supporting_excerpt_or_reference.split("Quoted excerpt:", 1)[1]
            by_claim[item.claim_field] = quote
        # Support is checked against the whole cited page: the entries paraphrase,
        # so measuring only the 300-character excerpt would punish correct paraphrases.
        slugs = []
        for source_id in {item.source_id for item in evidence}:
            source = package.sources_by_id[source_id]
            slug = source.source_url.rstrip("/").rsplit("/", 1)[-1]
            slugs.append(slug)
        full_text = " ".join(by_claim.values()) + " " + " ".join(page_text(slug) for slug in slugs)
        scores = {
            "what_it_measures": support(test.what_it_measures, full_text),
            "why_it_is_ordered": support(test.why_it_is_ordered, full_text),
        }
        verdict = "supported" if min(scores.values()) >= 0.35 else "weak"
        rows.append((test.test_id, test.canonical_name, verdict, scores, test.review_status))

    supported = [row for row in rows if row[2] == "supported"]
    weak = [row for row in rows if row[2] == "weak"]
    no_quote = [row for row in rows if row[2] == "no-quote"]

    lines = [
        "# Knowledge evidence audit",
        "",
        "**Engineering check, not a clinical review.** For each entry the words of its",
        "claims are compared with the quoted excerpt from the cited page. A low score means",
        "the claim is not visibly traceable to the quote, and that entry is not promoted.",
        "",
        f"- entries: {len(rows)}",
        f"- supported (quotable evidence): **{len(supported)}**",
        f"- weak (quote does not carry the claim): {len(weak)}",
        f"- no quoted excerpt (source-level only): {len(no_quote)}",
        "",
    ]
    if supported:
        lines += ["## Supported", "", "| entry | what | why |", "|---|---|---|"]
        for test_id, name, _verdict, scores, _status in supported:
            lines.append(f"| `{test_id}` | {scores['what_it_measures']:.0%} | {scores['why_it_is_ordered']:.0%} |")
        lines.append("")
    if weak:
        lines += ["## Weak — needs a better excerpt or a reworded claim", ""]
        for test_id, name, _verdict, scores, _status in weak:
            lines.append(f"- `{test_id}` ({name}): {scores}")
        lines.append("")

    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines))
    print(f"wrote {REPORT}: {len(supported)} supported, {len(weak)} weak, {len(no_quote)} without quote")

    if args.apply:
        AUDIT_LOG.parent.mkdir(exist_ok=True)
        with AUDIT_LOG.open("a") as log:
            for test_id, _name, _verdict, scores, status in supported:
                if status != "draft":
                    continue
                code = cli.main([
                    "set-status", "--package", str(PACKAGE), "--test-id", test_id,
                    "--status", "reviewed",
                    "--reviewer", "internal claim audit (engineering); clinical sign-off pending",
                    "--note", f"claimed text traceable to quoted source excerpt (scores {scores})",
                ])
                if code == 0:
                    log.write(json.dumps({
                        "test_id": test_id,
                        "audit": "claim text traceable to quoted source excerpt",
                        "scores": scores,
                        "reviewer": "internal claim audit (engineering)",
                        "clinical_signoff": "pending",
                    }) + "\n")
        print("marked supported entries as reviewed (not approved)")


if __name__ == "__main__":
    main()
