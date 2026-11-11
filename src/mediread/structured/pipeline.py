"""Structured extraction pipeline: ``mediread.extraction/1`` -> ``mediread.results/1``.

Input is the ingestion contract (a dict loaded from an extraction artefact, or a
`DocumentExtraction`). The layer never re-opens the PDF and never calls OCR, so
it works identically on embedded text, OCR text and hybrid pages — the origin is
carried on the evidence instead.

Flow::

    DocumentExtraction
      -> per page: row reconstruction + header-derived column map   (rows.py)
      -> per block: state machine -> candidates + rejected rows     (extract.py)
      -> per candidate: four independent fields                     (extract.py)
      -> cross-field validation, duplicates, conflicts              (validate.py)
      -> ResultDocument
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from ..models import DocumentExtraction, PageExtraction, TextLine, TextWord, BBox
from . import vocabulary as vocab
from .extract import Rejected, build_result, collect_candidates, headerless_candidates
from .rows import PageTables, build_page_tables
from .schema import FieldStatus, LabResult, ResultDocument, Section, UnparsedRow
from .validate import resolve_duplicates, validate_result


def _line_from_dict(data: dict[str, Any]) -> TextLine:
    words = [
        TextWord(
            text=w.get("text", ""),
            bbox=BBox(*w["bbox"]),
            confidence=w.get("confidence"),
        )
        for w in data.get("words", []) or []
    ]
    return TextLine(
        text=data.get("text", ""),
        bbox=BBox(*data["bbox"]),
        words=words,
        confidence=data.get("confidence"),
        origin=data.get("origin", "embedded"),
    )


def page_from_dict(data: dict[str, Any]) -> PageExtraction:
    """Reconstruct the minimal page object the structured layer needs."""
    from ..models import PageClass, PageStats

    stats_data = data.get("stats") or {}
    stats = PageStats(
        page_number=data["page_number"],
        width_pt=data.get("width_pt", 0.0),
        height_pt=data.get("height_pt", 0.0),
        rotation=stats_data.get("rotation", 0),
        char_count=stats_data.get("char_count", 0),
        word_count=stats_data.get("word_count", 0),
        text_block_count=stats_data.get("text_block_count", 0),
        text_area_ratio=stats_data.get("text_area_ratio", 0.0),
        image_count=stats_data.get("image_count", 0),
        image_area_ratio=stats_data.get("image_area_ratio", 0.0),
        largest_image_px=None,
        vector_path_count=stats_data.get("vector_path_count", 0),
        horizontal_rule_count=stats_data.get("horizontal_rule_count", 0),
        vertical_rule_count=stats_data.get("vertical_rule_count", 0),
        font_names=stats_data.get("font_names", []),
        font_size_min=None,
        font_size_max=None,
        text_alpha_ratio=0.0,
        text_digit_ratio=0.0,
        unique_char_ratio=0.0,
        suspicious_text=False,
        page_class=PageClass(data.get("page_class", "unknown")),
        page_class_reason="loaded from extraction artefact",
        has_embedded_fonts=False,
    )
    return PageExtraction(
        report_id=data["report_id"],
        page_number=data["page_number"],
        source_kind=_source_kind(data.get("source_kind")),
        method=_extraction_method(data.get("method")),
        page_class=PageClass(data.get("page_class", "unknown")),
        width_pt=data.get("width_pt", 0.0),
        height_pt=data.get("height_pt", 0.0),
        text=data.get("text", ""),
        lines=[_line_from_dict(l) for l in data.get("lines", [])],
        stats=stats,
        warnings=data.get("warnings", []),
    )


def _source_kind(value: str | None):
    from ..models import SourceKind

    try:
        return SourceKind(value or "digital_pdf")
    except ValueError:
        return SourceKind.DIGITAL_PDF


def _extraction_method(value: str | None):
    from ..models import ExtractionMethod

    try:
        return ExtractionMethod(value or "embedded_text")
    except ValueError:
        return ExtractionMethod.EMBEDDED_TEXT


def document_from_dict(data: dict[str, Any]) -> DocumentExtraction:
    from ..models import SourceKind

    return DocumentExtraction(
        report_id=data["report_id"],
        source_filename=data.get("source_filename", ""),
        source_kind=_source_kind(data.get("source_kind")),
        page_count=data.get("page_count", len(data.get("pages", []))),
        pages=[page_from_dict(p) for p in data.get("pages", [])],
        engine_summary=data.get("engine_summary", {}) or {},
        warnings=data.get("warnings", []) or [],
    )


class StructuredExtractionPipeline:
    """Turns an ingestion document into validated laboratory results."""

    def __init__(self, *, allow_headerless: bool = True) -> None:
        self.allow_headerless = allow_headerless

    def process(
        self,
        document: DocumentExtraction | dict[str, Any],
        *,
        pages: list[int] | None = None,
        generated_at: str | None = None,
    ) -> ResultDocument:
        started = time.perf_counter()
        doc = document_from_dict(document) if isinstance(document, dict) else document
        wanted = set(pages) if pages else None

        results: list[LabResult] = []
        unparsed: list[UnparsedRow] = []
        sections: dict[str, Section] = {}
        pages_with_results = 0
        warnings: list[str] = []

        for page in doc.pages:
            if wanted and page.page_number not in wanted:
                continue
            if not page.lines:
                continue
            tables = build_page_tables(
                page.page_number, page.lines, page.width_pt, page.height_pt
            )
            if tables.blocks:
                candidates, rejected = collect_candidates(tables)
            elif self.allow_headerless:
                candidates, rejected = headerless_candidates(tables)
            else:
                candidates, rejected = [], []

            page_warnings: list[str] = []
            for rejection in rejected:
                unparsed.append(
                    UnparsedRow(
                        page=rejection.page,
                        text=rejection.text,
                        bbox=rejection.bbox,
                        reason=rejection.reason,
                    )
                )

            page_results: list[LabResult] = []
            for candidate in candidates:
                section = self._section_for(candidate, tables)
                result = build_result(
                    candidate,
                    page=page.page_number,
                    report_id=doc.report_id,
                    section=section.value,
                )
                validate_result(result)
                page_results.append(result)
                key = section.value
                if key not in sections:
                    sections[key] = Section(
                        name=section.value,
                        page=page.page_number,
                        basis="heading or test vocabulary",
                    )
            page_results = resolve_duplicates(page_results)
            if page_results:
                pages_with_results += 1
            results.extend(page_results)

        # Section counts are derived from the surviving results, after duplicate
        # resolution. Incrementing while walking candidates over-counted whenever
        # a duplicate row was removed.
        section_counts: dict[str, int] = {}
        for result in results:
            section_counts[result.section] = section_counts.get(result.section, 0) + 1
        for section in sections.values():
            section.result_count = section_counts.get(section.name, 0)

        document = ResultDocument(
            report_id=doc.report_id,
            source_filename=doc.source_filename,
            results=results,
            sections=list(sections.values()),
            unparsed_rows=unparsed,
            pages_processed=len([p for p in doc.pages if not wanted or p.page_number in wanted]),
            pages_with_results=pages_with_results,
            warnings=warnings,
            engine_summary=doc.engine_summary,
            generated_at=generated_at or _utc_now(),
        )
        document.stats = _stats(document)
        document.stats["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        return document

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _section_for(candidate, tables: PageTables) -> vocab.Section:
        if candidate.heading:
            lowered = candidate.heading.lower()
            for section, keywords in vocab.SECTION_KEYWORDS.items():
                if any(keyword in lowered for keyword in keywords):
                    return section
        match = vocab.match_test(candidate.test_text)
        if match.entry:
            return match.entry.section
        return vocab.section_for_test(candidate.test_text)

def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stats(document: ResultDocument) -> dict[str, Any]:
    total = len(document.results)
    by_status: dict[str, int] = {}
    for result in document.results:
        by_status[result.status.value] = by_status.get(result.status.value, 0) + 1
    verified = sum(1 for r in document.results if r.status is FieldStatus.VERIFIED)
    review = sum(
        1
        for r in document.results
        if r.status in (FieldStatus.REQUIRES_REVIEW, FieldStatus.UNCERTAIN)
    )
    invalid = sum(1 for r in document.results if r.status is FieldStatus.INVALID)
    field_statuses: dict[str, dict[str, int]] = {}
    for name in ("test", "value", "unit", "reference"):
        counts: dict[str, int] = {}
        for result in document.results:
            field = getattr(result, name)
            if field is None:
                continue
            counts[field.status.value] = counts.get(field.status.value, 0) + 1
        field_statuses[name] = counts
    return {
        "results": total,
        "results_by_status": by_status,
        "verified_results": verified,
        "review_results": review,
        "invalid_results": invalid,
        "review_rate": round(review / total, 3) if total else 0.0,
        "field_statuses": field_statuses,
        "unparsed_rows": len(document.unparsed_rows),
    }


def process_path(path: str | Path, *, pages: list[int] | None = None) -> ResultDocument:
    """Convenience: load an extraction artefact and process it."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return StructuredExtractionPipeline().process(data, pages=pages)
