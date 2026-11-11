"""Optional narration interface.

MediRead ships **no language model**. The deterministic templates produce the
explanation, and this module exists so that a future model can be added behind a
replaceable interface without weakening any guarantee.

A narrator may only rephrase text it is given. It never sees or produces numbers
that are not already in the facts bundle, and its output is validated with
:func:`mediread.explain.safety.validate_narrative` before use. On any validation
failure the deterministic text is used instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from . import safety
from .models import ExplanationDocument, ResultExplanation, Section, SectionKey


@dataclass(frozen=True)
class NarrativeBundle:
    """The only information a narrator is allowed to see."""

    result_id: str
    test_name: str
    education_text: str
    comparison_text: str | None
    limitations_text: str
    allowed_numbers: frozenset[str]
    approved_text: str


class Narrator(Protocol):
    name: str

    def narrate(self, bundle: NarrativeBundle) -> str:
        """Return rephrased education text."""


@dataclass
class DeterministicNarrator:
    """Default narrator: returns the composed text unchanged."""

    name: str = "deterministic"

    def narrate(self, bundle: NarrativeBundle) -> str:
        return bundle.education_text


@dataclass
class NarrativeResult:
    applied: bool
    narrator: str
    used_text: str
    findings: list[dict[str, str]] = field(default_factory=list)


def apply_narrator(
    document: ExplanationDocument,
    narrator: Narrator,
    *,
    bundles: dict[str, NarrativeBundle] | None = None,
) -> tuple[ExplanationDocument, list[NarrativeResult]]:
    """Rewrite education sections through a narrator, with validation.

    Returns the (possibly unchanged) document and one result per explanation.
    Any narrative that fails validation is discarded and the deterministic text
    is kept, so a model can never introduce an unsupported claim or number.
    """
    results: list[NarrativeResult] = []
    for explanation in document.results:
        education = explanation.section(SectionKey.WHAT_THIS_TEST_MEASURES)
        if not education.permitted or not education.text:
            continue
        bundle = (bundles or {}).get(explanation.result_id)
        if bundle is None:
            bundle = _bundle_for(explanation)
        proposed = narrator.narrate(bundle)
        findings = safety.validate_narrative(
            proposed,
            allowed_numbers=set(bundle.allowed_numbers),
            approved_text=bundle.approved_text,
        )
        if findings:
            results.append(
                NarrativeResult(
                    applied=False,
                    narrator=getattr(narrator, "name", "unknown"),
                    used_text=education.text,
                    findings=[finding.to_dict() for finding in findings],
                )
            )
            continue
        _replace_section_text(explanation, SectionKey.WHAT_THIS_TEST_MEASURES, proposed)
        results.append(
            NarrativeResult(
                applied=True,
                narrator=getattr(narrator, "name", "unknown"),
                used_text=proposed,
            )
        )
    return document, results


def _bundle_for(explanation: ResultExplanation) -> NarrativeBundle:
    education = explanation.section(SectionKey.WHAT_THIS_TEST_MEASURES)
    comparison = explanation.section(SectionKey.COMPARISON_WITH_REFERENCE)
    limitations = explanation.section(SectionKey.IMPORTANT_LIMITATIONS)
    allowed = safety.allowed_numbers_for(explanation)
    return NarrativeBundle(
        result_id=explanation.result_id,
        test_name=explanation.test_name,
        education_text=education.text or "",
        comparison_text=comparison.text,
        limitations_text=limitations.text or "",
        allowed_numbers=frozenset(allowed),
        approved_text=" ".join(
            section.text or "" for section in explanation.sections
        ),
    )


def _replace_section_text(
    explanation: ResultExplanation, key: SectionKey, text: str
) -> None:
    for index, section in enumerate(explanation.sections):
        if section.key is key:
            explanation.sections[index] = Section(
                key=section.key,
                kind=section.kind,
                permitted=section.permitted,
                text=text,
                reason=section.reason,
                sources=section.sources,
                partial=section.partial,
            )
            return
