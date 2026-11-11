"""Safety validation for generated explanations.

Two independent guarantees:

1. **No unsupported claim categories.** Diagnosis, treatment advice, urgency
   judgements, prognosis and false reassurance are matched by explicit patterns
   and rejected.
2. **No invented numbers.** Every numeric token in a fact or comparison section
   must already appear in the report-derived facts for that result. The engine
   cannot introduce a value, unit or bound that was not in the report.

The validator is used by the pipeline (on composed text), by the tests, and by
:func:`validate_narrative` for any future model-written text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ExplanationDocument, SectionKey, SectionKind

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Finding:
    category: str
    detail: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        return {"category": self.category, "detail": self.detail, "snippet": self.snippet}


# Patterns are written to catch *claims to the user*, not neutral mentions in
# educational text ("a provider may change treatment" is allowed).
_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "diagnosis_claim",
        "states or implies a diagnosis",
        re.compile(
            r"\byou (?:probably |likely |definitely )?have (?:a|an|the )?"
            r"(?:disease|condition|disorder|infection|cancer|diabetes|anaemia|anemia|"
            r"deficiency|thalassemia|thalassaemia)\b"
            r"|\b(?:this|it|the result|this finding|the finding) "
            r"(?:means|indicates|confirms|shows|proves) (?:that )?you have\b"
            r"|\bdiagnosed with\b|\byou are (?:suffering|diagnosed)\b"
            r"|\bconfirms? (?:a|an|the) (?:disease|condition|diagnosis)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "treatment_advice",
        "gives treatment or medication advice",
        re.compile(
            r"\byou should (?:start|stop|take|increase|reduce|decrease|change|avoid|try)\b"
            r"|\b(?:start|stop|take|change) (?:taking )?(?:your )?(?:medication|medicine|"
            r"supplement|dose)\b"
            r"|\bincrease your dose\b|\bdecrease your dose\b|\bwe recommend\b"
            r"|\byou can (?:stop|start) taking\b",
            re.IGNORECASE,
        ),
    ),
    (
        "urgency_claim",
        "makes a clinical urgency judgement",
        re.compile(
            r"\b(?:emergency|immediately|urgent(?:ly)?|right away|call 911|"
            r"seek (?:medical )?attention|life[- ]threatening)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "prognosis_claim",
        "makes a prognosis",
        re.compile(
            r"\b(?:will develop|prognosis|life expectancy|will not survive|fatal)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "false_reassurance",
        "offers false reassurance",
        re.compile(
            r"\b(?:you are (?:perfectly )?healthy|nothing to worry about|"
            r"no need to worry|perfectly normal|definitely normal|you are fine)\b",
            re.IGNORECASE,
        ),
    ),
)

# Text that legitimately mentions these concepts in a negated or neutral way.
_ALLOWED_CONTEXTS = (
    "not a medical diagnosis",
    "not a diagnosis",
    "does not replace advice",
    "cannot assess how urgent",
    "cannot assess",
)


# A claim is only a claim when it is asserted. Refusals and negations naturally
# contain the same words ("MediRead cannot say if you have anaemia"), so a match
# inside a negated clause must not be reported. This was a real false positive
# found while evaluating an LLM refusal; see docs/llm_evaluation.md.
_CLAUSE_SPLIT = re.compile(r"(?:[.;!?]\s+|\bbut\b|\bhowever\b|,)\s*", re.IGNORECASE)
_NEGATION_CUES = (
    "not ", "cannot", "can't", "won't", "no ", "never", "without", "unable",
    "isn't", "doesn't", "don't", "didn't", "neither", "nor ",
)


def _negated(sentence: str, index: int) -> bool:
    # Models often emit typographic apostrophes ("can’t"), which would otherwise
    # defeat the negation cue list. Normalise before matching.
    sentence = sentence.replace("\u2019", "'").replace("\u2018", "'")
    prefix = sentence[:index]
    parts = _CLAUSE_SPLIT.split(prefix)
    clause = (parts[-1] if parts else prefix).lower()
    return any(cue in clause for cue in _NEGATION_CUES)


def _iter_sentences(text: str):
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        yield sentence.strip()


def scan_text(text: str) -> list[Finding]:
    """Return safety findings for arbitrary text."""
    findings: list[Finding] = []
    for sentence in _iter_sentences(text):
        lowered = sentence.lower()
        if any(context in lowered for context in _ALLOWED_CONTEXTS):
            continue
        for category, detail, pattern in _RULES:
            for match in pattern.finditer(sentence):
                if _negated(sentence, match.start()):
                    continue
                findings.append(Finding(category, detail, sentence[:240]))
                break
    return findings


def numbers_in(text: str) -> set[str]:
    return {match.group(0) for match in _NUMBER.finditer(text)}


def validate_section_numbers(section_text: str, allowed_numbers: set[str]) -> list[Finding]:
    """Fact and comparison sections may only repeat numbers from the report."""
    findings: list[Finding] = []
    for token in numbers_in(section_text):
        if token not in allowed_numbers:
            findings.append(
                Finding(
                    category="invented_number",
                    detail=f"number '{token}' does not appear in the report facts",
                    snippet=section_text[:240],
                )
            )
    return findings


def allowed_numbers_from_view(view) -> set[str]:
    """Numbers a composer may repeat, taken from the report view itself."""
    numbers: set[str] = set()
    # The test name is part of the report fact and may itself contain digits
    # ("CA-125", "HbA1c", "T4"); those are identifiers, not measurements.
    for part in (
        view.value_text or "",
        view.unit_text or "",
        view.reference_text or "",
        view.test_name or "",
    ):
        numbers |= numbers_in(part)
    return numbers


def allowed_numbers_for(result) -> set[str]:
    """Numbers the engine was permitted to repeat for one explanation."""
    numbers = set(getattr(result, "allowed_numbers", ()) or ())
    comparison = getattr(result, "comparison", None)
    if comparison is not None:
        for bound in (comparison.low, comparison.high):
            if bound is not None:
                numbers |= numbers_in(str(bound))
    return numbers


def validate_document(document: ExplanationDocument) -> list[Finding]:
    """Full safety validation of a composed explanation document."""
    findings: list[Finding] = []
    for result in document.results:
        allowed = allowed_numbers_for(result)
        for section in result.sections:
            if not section.permitted or not section.text:
                continue
            findings.extend(scan_text(section.text))
            if section.kind in (SectionKind.FACT, SectionKind.COMPARISON):
                findings.extend(validate_section_numbers(section.text, allowed))
    return findings


def validate_narrative(
    narrative: str,
    *,
    allowed_numbers: set[str],
    approved_text: str,
) -> list[Finding]:
    """Validate model-written text before it may be shown.

    Any number must already exist either in the report facts or in the approved
    knowledge text supplied to the model. This is what stops a language model
    from rewriting a measurement.
    """
    findings = scan_text(narrative)
    approved_numbers = allowed_numbers | numbers_in(approved_text)
    findings.extend(validate_section_numbers(narrative, approved_numbers))
    return findings


def is_safe(document: ExplanationDocument) -> bool:
    return not validate_document(document)
