"""Serialisation of explanation documents (``mediread.explanation/1``).

Explanations contain laboratory content and are written only under an explicit
local output directory. Logs never receive this content.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import SCHEMA_VERSION, ExplanationDocument


def write_explanations(
    document: ExplanationDocument,
    out_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{document.report_id}.explanations.json"
    path.write_text(
        json.dumps(document.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    run = {
        "schema_version": SCHEMA_VERSION,
        "report_id": document.report_id,
        "source_filename": document.source_filename,
        "generated_at": document.generated_at,
        "contract_version": document.contract_version,
        "knowledge_version": document.knowledge_version,
        "stats": document.stats,
        "config": config or {},
    }
    (out_dir / f"{document.report_id}.explanations.run.json").write_text(
        json.dumps(run, indent=2), encoding="utf-8"
    )
    return path


def load_explanations(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
