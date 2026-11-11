"""Downstream contract: the only interface the explanation engine may use.

Why a projection instead of handing over ``ResultDocument`` directly
---------------------------------------------------------------------
``ResultDocument`` is an internal model. It carries extraction concerns —
per-page statistics, engine summaries, rejected rows, parser diagnostics — that a
consumer must not depend on, and it can change between extraction releases. This
module defines a small, versioned, frozen view:

    mediread.results/1  --(load)-->  ResultDocument  --(project)-->  ExplanationInput

A consumer imports :mod:`mediread.structured.contract` and nothing else. It never
sees PDFs, OCR engines, table geometry or parser internals, and the extraction
implementation can be replaced as long as it produces ``mediread.results/1``.

What the projection guarantees
------------------------------
* Every field keeps its **original text** next to its normalized form and status.
* ``verified`` / ``uncertain`` / ``requires_review`` / ``missing`` / ``invalid``
  remain distinguishable per field and per result.
* Source evidence (page, bounding box, origin) travels with each field, so a
  review screen can highlight it.
* Serialization is deterministic: the same document produces byte-identical JSON.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field as dc_field
from pathlib import Path
from typing import Any, Iterator

from .schema import (
    ContractError,
    Evidence,
    Field,
    FieldStatus,
    LabResult,
    ResultDocument,
    SUPPORTED_SCHEMA_VERSIONS,
)

CONTRACT_VERSION = "mediread.explanation-input/1"


# --------------------------------------------------------------------------
# Frozen views
# --------------------------------------------------------------------------


_NO_UNIT_MARKERS = {"-", "--", "---", "—", "n/a", "na", "nil"}


@dataclass(frozen=True)
class UsageGate:
    """Permission to perform one specific downstream action.

    ``allowed`` is never true merely because the *result* is verified: each gate
    lists the fields it depends on, and any one of them not being verified blocks
    the action.
    """

    allowed: bool
    blocked_by: tuple[str, ...] = ()
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked_by": list(self.blocked_by),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResultGates:
    """What a consumer may do with this result without further confirmation."""

    identify_test: UsageGate
    interpret_value: UsageGate
    unit_comparison: UsageGate
    range_comparison: UsageGate

    @classmethod
    def blocked(cls, reason: str = "not evaluated") -> "ResultGates":
        gate = UsageGate(False, (), reason)
        return cls(gate, gate, gate, gate)

    def to_dict(self) -> dict[str, Any]:
        return {
            "identify_test": self.identify_test.to_dict(),
            "interpret_value": self.interpret_value.to_dict(),
            "unit_comparison": self.unit_comparison.to_dict(),
            "range_comparison": self.range_comparison.to_dict(),
        }


@dataclass(frozen=True)
class EvidenceView:
    page: int
    bbox: tuple[float, ...]
    text: str
    origin: str                      # "embedded" | "ocr"
    confidence: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "bbox": list(self.bbox),
            "text": self.text,
            "origin": self.origin,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class FieldView:
    """One value-bearing field, with source text and validation state."""

    text: str | None                 # verbatim source text; never rewritten
    status: str
    confidence: float
    normalized: str | None = None
    parsed: dict[str, Any] | None = None
    reasons: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    evidence: EvidenceView | None = None

    @property
    def is_verified(self) -> bool:
        return self.status == FieldStatus.VERIFIED.value

    def to_dict(self) -> dict[str, Any]:
        data = {
            "text": self.text,
            "status": self.status,
            "confidence": self.confidence,
            "normalized": self.normalized,
            "parsed": self.parsed,
            "reasons": list(self.reasons),
            "alternatives": list(self.alternatives),
            "evidence": self.evidence.to_dict() if self.evidence else None,
        }
        return data


@dataclass(frozen=True)
class ReferenceBounds:
    low: float | None
    high: float | None
    low_inclusive: bool
    high_inclusive: bool
    operator: str | None
    stratified: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResultView:
    result_id: str
    report_id: str
    page: int
    section: str
    test_name: str
    test_id: str | None
    value_text: str | None
    value_number: str | None          # decimal string, exact
    value_kind: str                   # numeric | qualitative | text | absent
    unit_text: str | None
    unit_canonical: str | None
    reference_text: str | None
    reference_bounds: ReferenceBounds | None
    qualitative_text: str | None
    status: str
    confidence: float
    fields: dict[str, FieldView]
    warnings: tuple[str, ...] = ()
    row_evidence: EvidenceView | None = None
    gates: ResultGates = dc_field(default_factory=ResultGates.blocked)

    @property
    def needs_review(self) -> bool:
        return self.status != FieldStatus.VERIFIED.value

    def field(self, name: str) -> FieldView:
        return self.fields[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "report_id": self.report_id,
            "page": self.page,
            "section": self.section,
            "test_name": self.test_name,
            "test_id": self.test_id,
            "value_text": self.value_text,
            "value_number": self.value_number,
            "value_kind": self.value_kind,
            "unit_text": self.unit_text,
            "unit_canonical": self.unit_canonical,
            "reference_text": self.reference_text,
            "reference_bounds": self.reference_bounds.to_dict() if self.reference_bounds else None,
            "qualitative_text": self.qualitative_text,
            "status": self.status,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "fields": {name: view.to_dict() for name, view in self.fields.items()},
            "row_evidence": self.row_evidence.to_dict() if self.row_evidence else None,
            "gates": self.gates.to_dict(),
        }


@dataclass(frozen=True)
class ExplanationInput:
    """Everything the explanation engine is allowed to see."""

    contract_version: str
    schema_version: str
    report_id: str
    source_filename: str
    generated_at: str | None
    results: tuple[ResultView, ...]
    warnings: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "source_filename": self.source_filename,
            "generated_at": self.generated_at,
            "sections": list(self.sections),
            "warnings": list(self.warnings),
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self) -> str:
        """Deterministic serialization (sorted keys, fixed separators)."""
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=2)

    def __len__(self) -> int:
        return len(self.results)

    def __iter__(self) -> Iterator[ResultView]:
        return iter(self.results)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def parse_document(payload: dict[str, Any], *, strict: bool = True) -> ResultDocument:
    """Validate and deserialize a ``mediread.results/<n>`` payload."""
    if not isinstance(payload, dict):
        raise ContractError("result document must be a JSON object")
    return ResultDocument.from_dict(payload, strict=strict)


def load_document(path: str | Path, *, strict: bool = True) -> ResultDocument:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"result document not found: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"invalid JSON in {path.name}: {exc}") from exc
    return parse_document(payload, strict=strict)


def load_results(path: str | Path, *, strict: bool = True) -> ExplanationInput:
    """One call from a result file to the explanation-engine input."""
    return build_explanation_input(load_document(path, strict=strict))


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------


def _evidence_view(evidence: Evidence | None) -> EvidenceView | None:
    if evidence is None:
        return None
    return EvidenceView(
        page=evidence.page,
        bbox=tuple(round(v, 2) for v in evidence.bbox),
        text=evidence.text,
        origin=evidence.origin,
        confidence=None if evidence.confidence is None else round(evidence.confidence, 4),
    )


def _field_view(field: Field) -> FieldView:
    return FieldView(
        text=field.raw,
        status=field.status.value,
        confidence=round(field.confidence, 3),
        normalized=field.normalized,
        parsed=field.parsed,
        reasons=tuple(field.reasons),
        alternatives=tuple(field.alternatives),
        evidence=_evidence_view(field.evidence),
    )


def _reference_bounds(result: LabResult) -> ReferenceBounds | None:
    parsed = result.reference.parsed or {}
    if not parsed:
        return None
    if (
        parsed.get("low") is None
        and parsed.get("high") is None
        and not parsed.get("stratified")
    ):
        return None
    return ReferenceBounds(
        low=parsed.get("low"),
        high=parsed.get("high"),
        low_inclusive=bool(parsed.get("low_inclusive", True)),
        high_inclusive=bool(parsed.get("high_inclusive", True)),
        operator=parsed.get("operator"),
        stratified=bool(parsed.get("stratified", False)),
    )


def _is_explicit_no_unit(view: FieldView) -> bool:
    """``"-"`` is a printed no-unit marker, not absent information."""
    text = (view.text or "").strip().lower()
    return view.status == FieldStatus.MISSING.value and text in _NO_UNIT_MARKERS


def _gate(
    requirements: list[tuple[str, FieldView]],
    *,
    allow_explicit_no_unit_for: str | None = None,
) -> UsageGate:
    """Build a gate from the fields it depends on.

    A field satisfies a gate only when it is both ``verified`` and not
    OCR-derived. ``allow_explicit_no_unit_for`` lets a test whose report prints
    ``-`` (e.g. urine pH) satisfy a unit-dependent comparison, because a printed
    no-unit marker is information rather than missing data.
    """
    blocked: list[str] = []
    reasons: list[str] = []
    for name, view in requirements:
        if name == allow_explicit_no_unit_for and _is_explicit_no_unit(view):
            continue
        # OCR-derived evidence is blocked regardless of status: the extraction
        # layer already caps it, and the gate must not be weaker than that rule.
        if view.evidence is not None and view.evidence.origin == "ocr":
            blocked.append(name)
            reasons.append(f"{name} is OCR-derived and must be confirmed")
            continue
        if not view.is_verified:
            blocked.append(name)
            reasons.append(f"{name} is {view.status}")
    return UsageGate(allowed=not blocked, blocked_by=tuple(blocked), reason="; ".join(reasons) or None)


def _gates_for(fields: dict[str, FieldView]) -> ResultGates:
    test = fields["test"]
    value = fields["value"]
    unit = fields["unit"]
    reference = fields["reference"]

    identify = _gate([("test", test)])
    interpret = _gate([("test", test), ("value", value)])
    unit_comparison = _gate([("test", test), ("value", value), ("unit", unit)])

    reference_parsed = reference.parsed or {}
    if reference_parsed.get("stratified"):
        range_gate = UsageGate(
            False,
            ("reference",),
            "reference is stratified; it is not a single numeric interval",
        )
    else:
        range_gate = _gate(
            [("test", test), ("value", value), ("reference", reference), ("unit", unit)],
            allow_explicit_no_unit_for="unit",
        )
    return ResultGates(
        identify_test=identify,
        interpret_value=interpret,
        unit_comparison=unit_comparison,
        range_comparison=range_gate,
    )


def project_result(result: LabResult) -> ResultView:
    """Project one internal result into the consumer-visible view."""
    fields = {
        "test": _field_view(result.test),
        "value": _field_view(result.value),
        "unit": _field_view(result.unit),
        "reference": _field_view(result.reference),
    }
    if result.qualitative is not None:
        fields["qualitative"] = _field_view(result.qualitative)

    value_number = None
    if result.value.parsed and result.value.parsed.get("value") is not None:
        value_number = str(result.value.parsed["value"])

    row_evidence = None
    if result.evidence_lines:
        first = result.evidence_lines[0]
        row_evidence = EvidenceView(
            page=result.page,
            bbox=tuple(round(float(v), 2) for v in first.get("bbox", result.row_bbox)),
            text=first.get("text", ""),
            origin=first.get("origin", "embedded"),
            confidence=None,
        )

    gates = _gates_for(fields)

    return ResultView(
        result_id=result.result_id,
        report_id=result.report_id,
        page=result.page,
        section=result.section,
        test_name=result.test.raw or "",
        test_id=result.test.normalized,
        value_text=result.value.raw,
        value_number=value_number,
        value_kind=result.value_kind.value,
        unit_text=result.unit.raw,
        unit_canonical=result.unit.normalized,
        reference_text=result.reference.raw,
        reference_bounds=_reference_bounds(result),
        qualitative_text=result.qualitative.raw if result.qualitative else None,
        status=result.status.value,
        confidence=round(result.confidence, 3),
        fields=fields,
        warnings=tuple(result.warnings),
        row_evidence=row_evidence,
        gates=gates,
    )


def build_explanation_input(document: ResultDocument) -> ExplanationInput:
    """Project a whole document. No extraction internals survive this call."""
    if document.generated_at is None:
        # Older payloads have no timestamp; keep the field present but explicit.
        generated = None
    else:
        generated = document.generated_at
    return ExplanationInput(
        contract_version=CONTRACT_VERSION,
        schema_version=SUPPORTED_SCHEMA_VERSIONS[0],
        report_id=document.report_id,
        source_filename=document.source_filename,
        generated_at=generated,
        results=tuple(project_result(result) for result in document.results),
        warnings=tuple(document.warnings),
        sections=tuple(section.name for section in document.sections),
    )


def require_contract_version(version: str) -> None:
    """Reject an incompatible consumer contract rather than mis-reading it."""
    if version != CONTRACT_VERSION:
        raise ContractError(
            f"unsupported contract_version {version!r}; expected {CONTRACT_VERSION!r}"
        )
