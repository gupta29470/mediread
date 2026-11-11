"""Structured laboratory-result schema (``mediread.results/1``).

The schema exists to answer four questions for every field:

1. What exactly was on the page?        -> ``Field.raw`` + ``Evidence``
2. What do we think it means?           -> ``Field.normalized`` / ``Field.parsed``
3. How much do we trust it?             -> ``Field.status`` + ``Field.confidence``
4. Why?                                 -> ``Field.reasons``

A field is never "verified" because parsing produced a value. Verification is a
rule decision that requires: exact evidence, an unambiguous association, a
recognised vocabulary term (where a vocabulary exists) and no competing
candidate. Everything else is explicitly ``uncertain``, ``missing``,
``invalid`` or ``requires_review`` so a review screen can surface it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field, asdict
from enum import Enum
from typing import Any


SCHEMA_VERSION = "mediread.results/1"
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_VERSION,)


class ContractError(ValueError):
    """Raised when a serialized result document violates the schema contract."""


class FieldStatus(str, Enum):
    VERIFIED = "verified"
    UNCERTAIN = "uncertain"
    MISSING = "missing"
    INVALID = "invalid"
    REQUIRES_REVIEW = "requires_review"


# Severity ordering used to aggregate a result from its fields.
_STATUS_RANK = {
    FieldStatus.VERIFIED: 0,
    FieldStatus.MISSING: 1,
    FieldStatus.UNCERTAIN: 2,
    FieldStatus.REQUIRES_REVIEW: 3,
    FieldStatus.INVALID: 4,
}


def worst_status(statuses: list[FieldStatus]) -> FieldStatus:
    """Aggregate status: the most severe field status wins.

    A missing unit matters less than a contradictory unit, and an invalid value
    matters most. Missing is ranked below uncertain because "we did not find a
    unit" is a known gap, while "we are not sure this is the unit" is a hazard
    for a downstream reader.
    """
    if not statuses:
        return FieldStatus.MISSING
    return max(statuses, key=lambda s: _STATUS_RANK[s])


class ValueKind(str, Enum):
    NUMERIC = "numeric"
    QUALITATIVE = "qualitative"
    TEXT = "text"          # free text result we could not classify
    ABSENT = "absent"      # cell empty


def _require(data: dict[str, Any], key: str, context: str) -> Any:
    if key not in data:
        raise ContractError(f"{context}: missing required field '{key}'")
    return data[key]


def _status(value: str, context: str) -> FieldStatus:
    try:
        return FieldStatus(value)
    except ValueError as exc:
        allowed = ", ".join(s.value for s in FieldStatus)
        raise ContractError(f"{context}: invalid status '{value}' (allowed: {allowed})") from exc


@dataclass
class Evidence:
    """Where a field came from, exactly.

    ``text`` is the verbatim source substring (never normalised).
    """

    page: int
    bbox: list[float]
    text: str
    origin: str = "embedded"          # embedded | ocr
    confidence: float | None = None
    line_index: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], context: str = "evidence") -> "Evidence":
        return cls(
            page=int(_require(data, "page", context)),
            bbox=[float(v) for v in data.get("bbox", [])],
            text=data.get("text", ""),
            origin=data.get("origin", "embedded"),
            confidence=data.get("confidence"),
            line_index=data.get("line_index"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "bbox": [round(v, 2) for v in self.bbox],
            "text": self.text,
            "origin": self.origin,
            "confidence": None if self.confidence is None else round(self.confidence, 4),
            "line_index": self.line_index,
        }


@dataclass
class Field:
    """A single extracted field with its status, confidence and provenance."""

    raw: str | None = None
    status: FieldStatus = FieldStatus.MISSING
    confidence: float = 0.0
    reasons: list[str] = dc_field(default_factory=list)
    normalized: str | None = None
    parsed: dict[str, Any] | None = None
    evidence: Evidence | None = None
    alternatives: list[str] = dc_field(default_factory=list)

    @property
    def is_verified(self) -> bool:
        return self.status is FieldStatus.VERIFIED

    @classmethod
    def from_dict(cls, data: dict[str, Any], context: str = "field") -> "Field":
        evidence = data.get("evidence")
        return cls(
            raw=data.get("raw"),
            status=_status(_require(data, "status", context), context),
            confidence=float(data.get("confidence", 0.0)),
            reasons=list(data.get("reasons", [])),
            normalized=data.get("normalized"),
            parsed=data.get("parsed"),
            evidence=Evidence.from_dict(evidence, context) if evidence else None,
            alternatives=list(data.get("alternatives", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "reasons": list(self.reasons),
            "normalized": self.normalized,
            "parsed": self.parsed,
            "alternatives": list(self.alternatives),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }


@dataclass
class ReferenceRange:
    """Reference interval, preserving the original text and any parsed bounds.

    ``bounds`` is only populated when the interval is unambiguous. Stratified or
    qualitative references (``>=90: Normal``, ``Below 5.7%: Normal``) keep their
    text and set ``bounds=None`` with ``stratified=True``.
    """

    text: str | None = None
    low: float | None = None
    high: float | None = None
    low_inclusive: bool = True
    high_inclusive: bool = True
    operator: str | None = None      # "<", ">", "<=", ">=" for one-sided bounds
    low_text: str | None = None      # printed bound, decimal precision preserved
    high_text: str | None = None
    qualitative: str | None = None   # e.g. "Absent", "Pale Yellow"
    stratified: bool = False
    unit_hint: str | None = None
    parsed_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LabResult:
    """One laboratory test result with four independently assessed fields."""

    result_id: str
    report_id: str
    page: int
    section: str
    test: Field
    value: Field
    unit: Field
    reference: Field
    qualitative: Field | None = None
    method: str | None = None
    value_kind: ValueKind = ValueKind.NUMERIC
    row_bbox: list[float] = dc_field(default_factory=list)
    evidence_lines: list[dict[str, Any]] = dc_field(default_factory=list)
    status: FieldStatus = FieldStatus.UNCERTAIN
    confidence: float = 0.0
    warnings: list[str] = dc_field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.test.raw or self.test.normalized or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "report_id": self.report_id,
            "page": self.page,
            "section": self.section,
            "test": self.test.to_dict(),
            "value": self.value.to_dict(),
            "qualitative": self.qualitative.to_dict() if self.qualitative else None,
            "unit": self.unit.to_dict(),
            "reference": self.reference.to_dict(),
            "method": self.method,
            "value_kind": self.value_kind.value,
            "status": self.status.value,
            "confidence": round(self.confidence, 3),
            "row_bbox": [round(v, 2) for v in self.row_bbox],
            "evidence_lines": self.evidence_lines,
            "warnings": self.warnings,
        }


    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LabResult":
        context = f"result {data.get('result_id', '?')}"
        qualitative = data.get("qualitative")
        return cls(
            result_id=str(_require(data, "result_id", context)),
            report_id=str(_require(data, "report_id", context)),
            page=int(_require(data, "page", context)),
            section=data.get("section", ""),
            test=Field.from_dict(_require(data, "test", context), f"{context}.test"),
            value=Field.from_dict(_require(data, "value", context), f"{context}.value"),
            unit=Field.from_dict(_require(data, "unit", context), f"{context}.unit"),
            reference=Field.from_dict(_require(data, "reference", context), f"{context}.reference"),
            qualitative=Field.from_dict(qualitative, f"{context}.qualitative") if qualitative else None,
            method=data.get("method"),
            value_kind=ValueKind(data.get("value_kind", "numeric")),
            row_bbox=[float(v) for v in data.get("row_bbox", [])],
            evidence_lines=list(data.get("evidence_lines", [])),
            status=_status(_require(data, "status", context), context),
            confidence=float(data.get("confidence", 0.0)),
            warnings=list(data.get("warnings", [])),
        )


@dataclass
class Section:
    name: str
    page: int
    result_count: int = 0
    confidence: float = 0.5
    basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Section":
        return cls(
            name=str(_require(data, "name", "section")),
            page=int(data.get("page", 0)),
            result_count=int(data.get("result_count", 0)),
            confidence=float(data.get("confidence", 0.0)),
            basis=data.get("basis", ""),
        )


@dataclass
class UnparsedRow:
    """A row that looked like it could be a result but was not accepted.

    Kept on purpose: silent drops are how extraction bugs hide. The evaluation
    and the review screen can both inspect these.
    """

    page: int
    text: str
    bbox: list[float]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "text": self.text,
            "bbox": [round(v, 2) for v in self.bbox],
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UnparsedRow":
        return cls(
            page=int(data.get("page", 0)),
            text=data.get("text", ""),
            bbox=[float(v) for v in data.get("bbox", [])],
            reason=data.get("reason", ""),
        )


@dataclass
class ResultDocument:
    report_id: str
    source_filename: str
    results: list[LabResult] = dc_field(default_factory=list)
    sections: list[Section] = dc_field(default_factory=list)
    unparsed_rows: list[UnparsedRow] = dc_field(default_factory=list)
    pages_processed: int = 0
    pages_with_results: int = 0
    warnings: list[str] = dc_field(default_factory=list)
    stats: dict[str, Any] = dc_field(default_factory=dict)
    engine_summary: dict[str, Any] = dc_field(default_factory=dict)
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "report_id": self.report_id,
            "source_filename": self.source_filename,
            "generated_at": self.generated_at,
            "pages_processed": self.pages_processed,
            "pages_with_results": self.pages_with_results,
            "engine_summary": self.engine_summary,
            "stats": self.stats,
            "warnings": self.warnings,
            "sections": [s.to_dict() for s in self.sections],
            "results": [r.to_dict() for r in self.results],
            "unparsed_rows": [u.to_dict() for u in self.unparsed_rows],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, strict: bool = True) -> "ResultDocument":
        """Deserialize with contract validation.

        ``strict`` verifies the declared statistics against the records. Unknown
        extra keys are ignored so a newer producer adding a field does not break
        an older consumer; a different ``schema_version`` is rejected.
        """
        version = data.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ContractError(
                f"unsupported schema_version {version!r}; "
                f"this build reads {', '.join(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        document = cls(
            report_id=str(_require(data, "report_id", "document")),
            source_filename=data.get("source_filename", ""),
            results=[LabResult.from_dict(r) for r in data.get("results", [])],
            sections=[Section.from_dict(s) for s in data.get("sections", [])],
            unparsed_rows=[UnparsedRow.from_dict(u) for u in data.get("unparsed_rows", [])],
            pages_processed=int(data.get("pages_processed", 0)),
            pages_with_results=int(data.get("pages_with_results", 0)),
            warnings=list(data.get("warnings", [])),
            stats=dict(data.get("stats", {})),
            engine_summary=dict(data.get("engine_summary", {})),
            generated_at=data.get("generated_at"),
        )
        if strict:
            from .audit import audit_document

            report = audit_document(document)
            if not report["consistent"]:
                raise ContractError("; ".join(report["problems"]))
        return document
