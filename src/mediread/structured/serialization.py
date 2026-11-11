"""Serialisation of structured results (``mediread.results/1``).

Artefacts contain laboratory content and are therefore local-only, written under
an explicit output directory. Logs never receive this content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import SCHEMA_VERSION, ResultDocument


def write_results(
    document: ResultDocument,
    out_dir: str | Path,
    *,
    source_sha256: str | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = document.to_dict()
    path = out_dir / f"{document.report_id}.results.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    run = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "report_id": document.report_id,
        "source_filename": document.source_filename,
        "source_sha256": source_sha256,
        "config": config or {},
        "stats": document.stats,
    }
    (out_dir / f"{document.report_id}.results.run.json").write_text(
        json.dumps(run, indent=2), encoding="utf-8"
    )
    return path


def load_results(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
