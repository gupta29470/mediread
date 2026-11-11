"""JSON serialisation of ingestion output.

Two artefacts are produced per run:

* ``<report_id>.extraction.json`` — pages, text, boxes, confidences, page stats,
  engine metadata, timings and warnings. This is the contract with the future
  laboratory-extraction layer.
* ``<report_id>.run.json`` — run metadata: tool version, dependency versions,
  configuration, source file digest, timings. Enough to reproduce the run.

Text is written because the extraction contract requires it; the artefact is
therefore patient data and is written only under the local ``artifacts/`` tree.
Logs never contain it.
"""

from __future__ import annotations

import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import DocumentExtraction


def dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("pymupdf", "numpy", "PIL"):
        try:
            module = __import__(name)
            versions[name] = getattr(module, "__version__", "unknown")
        except Exception:  # pragma: no cover - optional
            versions[name] = "unavailable"
    return versions


def document_payload(document: DocumentExtraction, *, include_lines: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "mediread.extraction/1",
        "report_id": document.report_id,
        "source_filename": document.source_filename,
        "source_kind": document.source_kind.value,
        "page_count": document.page_count,
        "engine_summary": document.engine_summary,
        "warnings": document.warnings,
        "pages": [page.to_dict(include_lines=include_lines) for page in document.pages],
    }


def write_extraction(
    document: DocumentExtraction,
    out_dir: str | Path,
    *,
    include_lines: bool = True,
    config: dict[str, Any] | None = None,
    source_sha256: str | None = None,
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = document_payload(document, include_lines=include_lines)

    extraction_path = out_dir / f"{document.report_id}.extraction.json"
    extraction_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    run = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mediread_version": _package_version(),
        "dependencies": dependency_versions(),
        "config": config or {},
        "source_sha256": source_sha256,
        "report_id": document.report_id,
        "page_count": document.page_count,
        "engine_summary": document.engine_summary,
    }
    run_path = out_dir / f"{document.report_id}.run.json"
    run_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    return extraction_path, run_path


def _package_version() -> str:
    try:
        from .. import __version__

        return __version__
    except Exception:  # pragma: no cover
        return "unknown"
