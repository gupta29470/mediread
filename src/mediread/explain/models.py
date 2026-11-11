"""Explanation output model (``mediread.explanation/1``).

Every explanation is split into six named sections. Each section records whether
it was permitted, why, and which sources ground it, so a UI can render a partial
explanation without guessing and a reviewer can see exactly what was withheld.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dc_field
from enum import Enum
from typing import Any

SCHEMA_VERSION = "mediread.explanation/1"

DISCLAIMER = (
    "MediRead provides general educational information about laboratory reports. "
    "It is not a medical diagnosis and does not replace advice from a qualified "
    "health professional. Discuss your results with your doctor or the clinician "
    "who ordered the tests."
)

URGENCY_NOTICE = (
    "MediRead cannot assess how urgent any result is. If you feel unwell or are "
    "worried about a result, contact a healthcare professional."
)


class SectionKey(str, Enum):
    WHAT_THIS_TEST_MEASURES = "what_this_test_measures"
    YOUR_REPORTED_RESULT = "your_reported_result"
    COMPARISON_WITH_REFERENCE = "comparison_with_reference"
    WHAT_THIS_MAY_GENERALLY_INDICATE = "what_this_may_generally_indicate"
    IMPORTANT_LIMITATIONS = "important_limitations"
    SOURCES = "sources"


class SectionKind(str, Enum):
    EDUCATION = "education"      # general medical knowledge
    FACT = "fact"                # what this specific report prints
    COMPARISON = "comparison"    # deterministic comparison
    LIMITATION = "limitation"    # what cannot be concluded
    REFERENCE = "reference"      # sources


class ComparisonState(str, Enum):
    WITHIN_RANGE = "within_range"
    BELOW_RANGE = "below_range"
    ABOVE_RANGE = "above_range"
    SATISFIES_ONE_SIDED = "satisfies_one_sided_reference"
    VIOLATES_ONE_SIDED = "violates_one_sided_reference"
    MATCHES_QUALITATIVE_REFERENCE = "matches_qualitative_reference"
    DIFFERS_FROM_QUALITATIVE_REFERENCE = "differs_from_qualitative_reference"
    NOT_COMPARABLE_STRATIFIED = "not_comparable_stratified"
    NOT_COMPARABLE_MISSING_REFERENCE = "not_comparable_missing_reference"
    NOT_COMPARABLE_UNIT = "not_comparable_unit"
    NOT_COMPARABLE_VALUE = "not_comparable_value"
    BLOCKED_BY_GATE = "blocked_by_gate"


class ResultExplanationStatus(str, Enum):
    EXPLAINED = "explained"                  # education + result (+ comparison)
    PARTIALLY_EXPLAINED = "partially_explained"
    WITHHELD = "withheld"                    # nothing but limitations/evidence


@dataclass(frozen=True)
class Section:
    key: SectionKey
    kind: SectionKind
    permitted: bool
    text: str | None
    reason: str | None = None
    sources: tuple[str, ...] = ()
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key.value,
            "kind": self.kind.value,
            "permitted": self.permitted,
            "text": self.text,
            "reason": self.reason,
            "sources": list(self.sources),
            "partial": self.partial,
        }


@dataclass(frozen=True)
class Comparison:
    state: ComparisonState
    value_text: str
    unit_text: str | None
    reference_text: str | None
    low: float | None = None
    high: float | None = None
    low_inclusive: bool = True
    high_inclusive: bool = True
    operator: str | None = None
    stratified: bool = False
    description: str | None = None

    @property
    def is_decisive(self) -> bool:
        return self.state in {
            ComparisonState.WITHIN_RANGE,
            ComparisonState.BELOW_RANGE,
            ComparisonState.ABOVE_RANGE,
            ComparisonState.SATISFIES_ONE_SIDED,
            ComparisonState.VIOLATES_ONE_SIDED,
            ComparisonState.MATCHES_QUALITATIVE_REFERENCE,
            ComparisonState.DIFFERS_FROM_QUALITATIVE_REFERENCE,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data


@dataclass
class ResultExplanation:
    result_id: str
    report_id: str
    page: int
    section_name: str
    test_name: str
    test_id: str | None
    knowledge_status: str                     # supported | partial | unsupported
    status: ResultExplanationStatus
    permitted: dict[str, bool]
    gates: dict[str, bool]
    blocked_reasons: list[str]
    sections: list[Section]
    comparison: Comparison | None = None
    canonical_name: str | None = None
    warnings: list[str] = dc_field(default_factory=list)
    # Numeric tokens the composer was allowed to repeat for this result. Used by
    # the safety validator to detect an invented number.
    allowed_numbers: frozenset[str] = dc_field(default_factory=frozenset)

    def section(self, key: SectionKey) -> Section:
        for section in self.sections:
            if section.key is key:
                return section
        raise KeyError(key.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "report_id": self.report_id,
            "page": self.page,
            "section": self.section_name,
            "test_name": self.test_name,
            "test_id": self.test_id,
            "canonical_name": self.canonical_name,
            "knowledge_status": self.knowledge_status,
            "status": self.status.value,
            "permitted": dict(self.permitted),
            "gates": dict(self.gates),
            "blocked_reasons": list(self.blocked_reasons),
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "allowed_numbers": sorted(self.allowed_numbers),
            "sections": [section.to_dict() for section in self.sections],
            "warnings": list(self.warnings),
        }


@dataclass
class ExplanationDocument:
    report_id: str
    source_filename: str
    results: list[ResultExplanation] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    stats: dict[str, Any] = dc_field(default_factory=dict)
    generated_at: str | None = None
    contract_version: str = ""
    knowledge_version: str = ""
    disclaimer: str = DISCLAIMER
    urgency_notice: str = URGENCY_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "contract_version": self.contract_version,
            "knowledge_version": self.knowledge_version,
            "mode": "deterministic",
            "report_id": self.report_id,
            "source_filename": self.source_filename,
            "generated_at": self.generated_at,
            "disclaimer": self.disclaimer,
            "urgency_notice": self.urgency_notice,
            "stats": self.stats,
            "warnings": list(self.warnings),
            "results": [result.to_dict() for result in self.results],
        }
