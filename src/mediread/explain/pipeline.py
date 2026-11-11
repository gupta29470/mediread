"""Explanation engine orchestration.

    ExplanationInput (mediread.explanation-input/1)
        -> per result: knowledge lookup + deterministic comparison
        -> six composited sections
        -> safety validation (withholds any section that fails)
        -> ExplanationDocument (mediread.explanation/1)

The engine never imports ingestion or extraction modules; it depends only on the
frozen contract.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from ..structured.contract import ExplanationInput, ResultView
from . import safety
from .compose import explain_result
from .interpret import compare_result
from .knowledge.catalogue import CATALOGUE, KnowledgeCatalogue
from .model_input import build_model_input
from .models import (
    DISCLAIMER,
    SCHEMA_VERSION,
    URGENCY_NOTICE,
    ExplanationDocument,
    ResultExplanation,
    ResultExplanationStatus,
    Section,
    SectionKey,
    SectionKind,
)


class ExplanationEngine:
    """Deterministic explanation engine.

    ``catalogue`` keeps the original bundled-catalogue behaviour. Passing a
    ``PackageProvider`` switches knowledge to the versioned package and adds the
    versioned model-input document; the gates and safety validation are identical
    either way.
    """

    def __init__(
        self,
        catalogue: KnowledgeCatalogue | None = None,
        *,
        provider=None,
    ) -> None:
        self.catalogue = catalogue or CATALOGUE
        self.knowledge = provider or self.catalogue
        self.last_duration_ms: float = 0.0
        self.model_inputs: dict[str, dict[str, Any]] = {}
        if provider is not None:
            errors = tuple(getattr(provider, "errors", ()))
        else:
            errors = self.catalogue.errors
        if errors:
            raise ValueError("knowledge catalogue is invalid: " + "; ".join(errors))

    def explain(
        self,
        data: ExplanationInput,
        *,
        generated_at: str | None = None,
    ) -> ExplanationDocument:
        started = time.perf_counter()
        results = []
        self.model_inputs = {}
        for view in data:
            lookup = self.knowledge.lookup(view.test_id, view.test_name, view.section)
            results.append(explain_result(view, self.knowledge, lookup=lookup))
            if hasattr(self.knowledge, "evidence_for") and lookup.entry is not None:
                evidence = self.knowledge.evidence_for(lookup.entry.test_id)
                version = self.knowledge.version
            else:
                evidence = ()
                version = self.knowledge.version
            self.model_inputs[view.result_id] = build_model_input(
                view,
                lookup,
                compare_result(view),
                knowledge_version=version,
                evidence_ids=evidence,
            )

        document = ExplanationDocument(
            report_id=data.report_id,
            source_filename=data.source_filename,
            results=results,
            generated_at=generated_at or _utc_now(),
            contract_version=data.contract_version,
            knowledge_version=self.knowledge.version,
            disclaimer=DISCLAIMER,
            urgency_notice=URGENCY_NOTICE,
        )
        withheld = _enforce_safety(document)
        if withheld:
            document.warnings.append(
                f"{withheld} section(s) withheld by safety validation"
            )
        document.stats = _stats(document)
        # Timing is run metadata, not part of the explanation payload: keeping it
        # out of ``stats`` is what makes two runs byte-identical.
        self.last_duration_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return document


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_SAFE_FALLBACK = (
    "MediRead withheld part of this explanation because it did not pass its safety "
    "check. Please rely on the original report and your health professional."
)


def _enforce_safety(document: ExplanationDocument) -> int:
    """Withhold any section whose text violates a safety rule.

    Defence in depth: composed text should already be safe, but if a template
    regresses the unsafe section is replaced rather than shown.
    """
    withheld = 0
    for explanation in document.results:
        for index, section in enumerate(explanation.sections):
            if not section.permitted or not section.text:
                continue
            findings = safety.scan_text(section.text)
            if section.kind in (SectionKind.FACT, SectionKind.COMPARISON):
                findings += safety.validate_section_numbers(
                    section.text, safety.allowed_numbers_for(explanation)
                )
            if findings:
                explanation.sections[index] = Section(
                    key=section.key,
                    kind=section.kind,
                    permitted=False,
                    text=_SAFE_FALLBACK,
                    reason="withheld by safety validation: "
                    + "; ".join(sorted({finding.category for finding in findings})),
                    sources=(),
                    partial=section.partial,
                )
                explanation.warnings.append(
                    f"section {section.key.value} withheld by safety validation"
                )
                withheld += 1
    return withheld


def _stats(document: ExplanationDocument) -> dict[str, Any]:
    total = len(document.results)
    by_status: dict[str, int] = {}
    knowledge: dict[str, int] = {}
    section_permitted: dict[str, int] = {key.value: 0 for key in SectionKey}
    for explanation in document.results:
        by_status[explanation.status.value] = by_status.get(explanation.status.value, 0) + 1
        knowledge[explanation.knowledge_status] = (
            knowledge.get(explanation.knowledge_status, 0) + 1
        )
        for section in explanation.sections:
            if section.permitted:
                section_permitted[section.key.value] += 1
    explained = by_status.get(ResultExplanationStatus.EXPLAINED.value, 0)
    partial = by_status.get(ResultExplanationStatus.PARTIALLY_EXPLAINED.value, 0)
    withheld = by_status.get(ResultExplanationStatus.WITHHELD.value, 0)
    return {
        "results": total,
        "by_status": by_status,
        "by_knowledge_status": knowledge,
        "sections_permitted": section_permitted,
        "fully_explained": explained,
        "partially_explained": partial,
        "withheld": withheld,
        "full_explanation_rate": round(explained / total, 4) if total else 0.0,
    }
